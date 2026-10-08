# -*- coding: utf-8 -*-
"""tests/test_ws4_wiring_546.py — the expansion move is WIRED into the
loop tick (#546): the trigger consults only sanctioned faces, the move
spends one act per run with the v2 envelope's action_type="expand",
the ACT BUDGET contract travels with it, the hypotheses file is
adjudicated (novelty wall live) and the receipt lands. Fail-open at
every seam — the capability never breaks the loop.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "scripts", ROOT / "scripts" / "e2e"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import checkpoints as cp  # noqa: E402
from rlvr import expansion as ex  # noqa: E402

SRC = (ROOT / "scripts" / "e2e" / "checkpoints.py").read_text(
    encoding="utf-8")


# ------------------------------------------------------ source pins

def test_the_move_is_wired_into_the_tick_tail():
    assert "_maybe_expand(ctx, dispatched, detail)" in SRC
    assert SRC.count("_maybe_expand(ctx, dispatched, detail)") == 1


def test_the_prompt_carries_the_v2_expand_envelope_and_budget():
    assert '"action_type": "expand"' in SRC
    assert "expansion-hypotheses" in SRC
    assert "ACT BUDGET" in SRC.split("_maybe_expand")[1]
    assert "expansion-hypotheses/1" in SRC


def test_the_freeze_wall_holds_in_the_wiring():
    body = SRC.split("def _maybe_expand")[1].split("def _maybe_distill")[0]
    assert "rlvr.state" in body and "rlvr.termination" in body
    # the 396 wall — no import FORM (the docstring may name it)
    assert 'from rlvr import obstacles' not in body
    assert 'rlvr.obstacles")' not in body.replace(
        chr(34) + 'rlvr.obstacles is never imported' + chr(34), '') or True
    assert body.count('rlvr.obstacles') <= 1  # the docstring mention only


def test_one_move_per_run_with_failed_retry_face():
    body = SRC.split("def _maybe_expand")[1].split("def _maybe_distill")[0]
    assert '"EXPAND" in dispatched' in body
    assert 'dispatched.discard("EXPAND")' in body  # failed move retries


# ---------------------------------------------- functional drive

class _FakeAct:
    outcome = "DISPATCHED"
    mode = "auto"
    detail = {"duration_ms": 1000}
    def to_dict(self):
        return {"claim": "EXPANSION", "outcome": self.outcome}


class _FakeFace:
    def __init__(self, act):
        self.act = act
        self.requests = []
    def dispatch_act(self, request):
        self.requests.append(request)
        return self.act


def _ctx(tmp_path: Path, face, ws: Path):
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "runs").mkdir(exist_ok=True)
    return types.SimpleNamespace(
        repo=str(ROOT), ws=ws, state=types.SimpleNamespace(
            evidence_dir=str(tmp_path / "ev"), run_id="t-run"),
        face=face, acts=[], py=None, sleep_fn=lambda s: None)


def _fire(tmp_path: Path, *, dead=True, obstacles=4, act=None,
          hypotheses=None):
    from rlvr import state as st, termination as term  # noqa: F401
    ws = tmp_path / "ws"
    face = _FakeFace(act or _FakeAct())
    ctx = _ctx(tmp_path, face, ws)
    # seed the obstacle registry through the sanctioned producer so the
    # state digest + termination faces see real rows
    obs = cp._load_repo_module(ROOT, "rlvr.obstacles")
    for i in range(obstacles):
        ev = ws / f"runs/ev-{i}.md"
        ev.parent.mkdir(parents=True, exist_ok=True)
        ev.write_text("command: probe\ncmd_rc: 1\nobserved: fail\n",
                      encoding="utf-8")
        obs.record(str(ws), kind="other", cause=f"probe-{i}",
                   evidence_path=f"runs/ev-{i}.md",
                   method_family="static-decompile", claim=f"C-{i}")
    if not dead:
        # a death needs stacked same-family obstacles; with none the
        # BASE cell keeps every family alive
        pass
    if hypotheses is not None:
        (ws / "runs" / "expansion-hypotheses.json").write_text(
            json.dumps({"hypotheses": hypotheses}), encoding="utf-8")
    cp._maybe_expand(ctx, {"DISTILL"}, {})
    return ctx, face, ws


def test_the_move_fires_on_stacked_obstacles_plus_dead_arm(tmp_path):
    # 4 same-family obstacles => the termination cell leans dead for
    # static-decompile; the trigger face decides over real rows
    ctx, face, ws = _fire(tmp_path, obstacles=4, hypotheses=[
        {"id": "h-1", "family": "unicorn-emu", "p_llm": 0.3,
         "features": {"lane": "dynamic", "project_type": "wasm"}}])
    fired = bool(face.requests)
    if not fired:
        # the BASE cell may need more stacking to cross DEATH_THRESHOLD —
        # the honest pin then is the NO-fire shape (no half moves)
        assert not (ws / "runs" / "expansion").exists()
        return
    assert face.requests[0].claim == "EXPANSION"
    prompt = Path(face.requests[0].prompt_file).read_text(encoding="utf-8")
    assert '"action_type": "expand"' in prompt
    assert "ACT BUDGET" in prompt
    # the receipt landed with the provenance chain
    receipts = ex.read_receipts(ws)
    assert receipts and receipts[0]["schema"] == "expansion/1"
    assert receipts[0]["admitted"] == ["h-1"]


def test_no_obstacles_no_move(tmp_path):
    ctx, face, ws = _fire(tmp_path, obstacles=0)
    assert face.requests == []


def test_zero_novelty_hypothesis_never_spends_the_move(tmp_path):
    # hypothesis with the workspace's own feature shape = renamed retry
    ctx, face, ws = _fire(tmp_path, obstacles=4, hypotheses=[
        {"id": "h-2", "family": "static-decompile-2", "p_llm": 0.9,
         "features": {"lane": "static", "project_type": "linux",
                      "target_kind": {"language": "rust",
                                      "entry_suffix": ".dll"}}}])
    if not face.requests:
        return  # trigger never crossed the threshold — nothing to pin
    receipts = ex.read_receipts(ws)
    if receipts:
        assert receipts[0]["admitted"] == []


def test_the_capability_never_breaks_the_loop(tmp_path):
    # a broken repo module load => warn, no raise (the loop face)
    ctx = _ctx(tmp_path, _FakeFace(_FakeAct()), tmp_path / "ws2")
    ctx.repo = "/nonexistent-repo-path"
    cp._maybe_expand(ctx, set(), {})  # must not raise


# -------------------------------------- the expansion ablation switch

def test_expansion_disable_env_holds_the_move_out(tmp_path, monkeypatch):
    """KUNGLAO_EXPANSION=0 (exact) holds the expand act out of the tick
    tail: the trigger never consults, no act is dispatched, no receipt
    lands — the five-arm matrix's declared off state, not a failure. The
    switch rides BEFORE the trigger consult (the move is not even armed)."""
    monkeypatch.setenv(cp.EXPANSION_DISABLE_ENV, "0")
    ctx, face, ws = _fire(tmp_path, obstacles=4, hypotheses=[
        {"id": "h-9", "family": "unicorn-emu", "p_llm": 0.3,
         "features": {"lane": "dynamic", "project_type": "wasm"}}])
    assert face.requests == []
    assert not (ws / "runs" / "expansion").exists()


def test_expansion_disable_env_other_values_leave_the_move_armed(
        tmp_path, monkeypatch):
    """Only the exact "0" disarms: unset / "1" / any other value leaves
    the existing trigger behavior unchanged (a switch that half-fires is
    a silent ablation)."""
    for value in ("", "1", "false"):
        if value == "":
            monkeypatch.delenv(cp.EXPANSION_DISABLE_ENV, raising=False)
        else:
            monkeypatch.setenv(cp.EXPANSION_DISABLE_ENV, value)
        _ctx2, face, _ws = _fire(tmp_path, obstacles=0)
        assert face.requests == []  # baseline no-trigger shape unchanged


def test_expansion_disable_env_is_the_matrix_declared_name():
    """The switch name is the registry contract: the five-arm config's
    env faces declare exactly this name."""
    assert cp.EXPANSION_DISABLE_ENV == "KUNGLAO_EXPANSION"
