# -*- coding: utf-8 -*-
"""tests/test_absorb_settle_597.py — verify-act absorb-at-kill settlement.

Field evidence (the #594 kill measurement): 18 of 28 killed verify acts
had already written their verification-<claim>.md verdict to disk a
median 1182s before the 1800s-cap hard kill — the kill cuts the WRAP-UP,
not the work — yet the settle face dropped a bare 0.0 as if the act had
decided nothing (the go-arx round-2 BLOCKED loss was exactly this).

Pinned:
  1. kill WITH a parseable verdict on disk => settled from it: credit
     per the existing verify_credit mapping, o.absorbed_from_disk=true,
     the kill marker (o.status=TIMEOUT) retained.
  2. kill WITHOUT a verdict on disk => the bare kill, byte-identical
     row shape to today.
  3. refuted-on-disk => refuted credit (an absorbed refutation is still
     a refutation — no charity), absorb marker present for audit.
  4. unparseable / unknown verdict word => bare kill unchanged.
  5. the absorb is scoped to the act-timeout kill: BLOCKED acts keep
     today's bare settle.
  6. the ledger face owns the marker: default-off keeps every existing
     row byte-identical; the absorbable-word set is exactly
     {verified, confirmed, refuted}.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
for p in (SCRIPTS, SCRIPTS.parent / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from e2e import checkpoints, llm_faces, model  # noqa: E402
from rlvr import incremental_reward as ir  # noqa: E402
from test_e2e_runner import (ANCHORS, DERIVE_PY, FakeClock,  # noqa: E402
                             ScriptedRunner, TASK_YAML)


# ------------------------------------------------------------ fixtures

@pytest.fixture()
def stub_repo(tmp_path):
    """Minimal unit repo (same shape as test_redteam_face_501's)."""
    repo = tmp_path / "repo"
    task = repo / "eval/v1/tasks/smoke/py-derive-v1"
    (task / "target").mkdir(parents=True)
    (task / "target/derive.py").write_text(DERIVE_PY, encoding="utf-8")
    (task / "task.yaml").write_text(TASK_YAML, encoding="utf-8")
    (repo / "scripts").mkdir()
    return repo


@pytest.fixture()
def ctx(stub_repo, tmp_path):
    ws = tmp_path / "ws"
    ev_dir = tmp_path / "ev"
    ws.mkdir()
    (ws / "runs").mkdir()
    state = model.RunState(
        run_id="a1", unit="py-derive-v1", family="smoke",
        repo=str(stub_repo),
        task_dir=str(stub_repo / "eval/v1/tasks/smoke/py-derive-v1"),
        ws=str(ws), evidence_dir=str(ev_dir), budget_seconds=10_000,
        llm_mode="auto", started_ts="t", started_monotonic=0.0,
        anchors=dict(ANCHORS))
    runner = _KilledAtCapRunner()
    return checkpoints.RunContext(
        state=state, runner=runner,
        face=llm_faces.face_for("auto", runner, ev_dir),
        clock=FakeClock(), sleep_fn=lambda _s: None)


class _KilledAtCapRunner(ScriptedRunner):
    """The verify act is hard-killed at the act budget cap (rc -1,
    timed_out) — the 1799-1801s kill shape from the field measurement."""

    def run(self, cmd, cwd=None, timeout=None):
        argv = " ".join(str(c) for c in cmd)
        if "-p" in argv and "claim: " in argv:
            self.calls.append(argv)
            return model.CmdOutcome(rc=-1, stdout="",
                                    stderr="TIMEOUT after 1800s",
                                    timed_out=True)
        return super().run(cmd, cwd=cwd, timeout=timeout)


def _rows(ws: Path) -> list[dict]:
    p = Path(ws) / "runs" / "transitions.jsonl"
    if not p.is_file():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8")
            .splitlines() if l.strip()]


def _write_verdict(ws: Path, claim: str, verdict: str) -> None:
    (Path(ws) / "runs" / f"verification-{claim}.md").write_text(
        f"---\nclaim: {claim}\nverdict: {verdict}\n"
        "verification_mode: replay_probe\n---\n\nreplay face\n",
        encoding="utf-8")


# ------------------------------------------ 1. kill with verdict on disk

def test_kill_with_verified_on_disk_settles_the_verdict(ctx):
    _write_verdict(ctx.ws, "C-002", "verified")
    checkpoints._run_verifier_act(ctx, "C-002", set(), {"acts": []})
    rows = _rows(ctx.ws)
    assert len(rows) == 1
    row = rows[0]
    assert row["action_type"] == "verify"
    assert row["o"]["status"] == "TIMEOUT"          # kill marker retained
    assert row["o"]["absorbed_from_disk"] is True   # absorb marker present
    assert row["r_settle"] == 1.0                   # credit per the mapping


def test_kill_with_confirmed_on_disk_settles_confirmed(ctx):
    _write_verdict(ctx.ws, "C-002", "confirmed")
    checkpoints._run_verifier_act(ctx, "C-002", set(), {"acts": []})
    row = _rows(ctx.ws)[0]
    assert row["r_settle"] == 1.0
    assert row["o"]["absorbed_from_disk"] is True


# ----------------------------------------- 2. kill without a verdict ----

def test_kill_without_verdict_on_disk_is_the_bare_kill(ctx):
    checkpoints._run_verifier_act(ctx, "C-003", set(), {"acts": []})
    rows = _rows(ctx.ws)
    assert len(rows) == 1
    row = rows[0]
    # byte-identical to today's bare-kill row: no absorb marker, exact
    # key set, zero credit
    assert row["o"] == {"status": "TIMEOUT", "class": "verify",
                        "facts": 0, "variant": "verify"}
    assert row["r_settle"] == 0.0
    assert set(row) == {"ts", "dispatch_id", "action_type", "s", "a",
                        "o", "s_prime_phi", "phi_before", "r_incr",
                        "r_settle", "done"}


def test_unparseable_note_keeps_the_bare_kill(ctx):
    (Path(ctx.ws) / "runs" / "verification-C-004.md").write_text(
        "# wrap-up cut mid-write; no verdict line landed\n",
        encoding="utf-8")
    checkpoints._run_verifier_act(ctx, "C-004", set(), {"acts": []})
    row = _rows(ctx.ws)[0]
    assert row["r_settle"] == 0.0
    assert "absorbed_from_disk" not in row["o"]


def test_unknown_verdict_word_keeps_the_bare_kill(ctx):
    _write_verdict(ctx.ws, "C-004", "pending")
    checkpoints._run_verifier_act(ctx, "C-004", set(), {"acts": []})
    row = _rows(ctx.ws)[0]
    assert row["r_settle"] == 0.0
    assert "absorbed_from_disk" not in row["o"]


# --------------------------------------- 3. refuted absorbs as refuted --

def test_refuted_on_disk_absorbs_as_refutation(ctx):
    _write_verdict(ctx.ws, "C-005", "refuted")
    checkpoints._run_verifier_act(ctx, "C-005", set(), {"acts": []})
    row = _rows(ctx.ws)[0]
    assert row["r_settle"] == 0.0        # absorbed refutation: no charity
    assert row["o"]["absorbed_from_disk"] is True
    assert row["o"]["status"] == "TIMEOUT"


# ------------------------------------- 4. scope: timeout kill only ------

def test_blocked_outcome_keeps_the_bare_settle(ctx, stub_repo, tmp_path):
    _write_verdict(ctx.ws, "C-006", "verified")
    runner = ScriptedRunner()
    runner.on("claude", "-p", rc=0, stdout='{"result": "Blocked: wall"}')
    ctx2 = checkpoints.RunContext(
        state=model.RunState(
            run_id="a1", unit="py-derive-v1", family="smoke",
            repo=str(stub_repo),
            task_dir=str(stub_repo / "eval/v1/tasks/smoke/py-derive-v1"),
            ws=str(ctx.ws), evidence_dir=str(tmp_path / "ev"),
            budget_seconds=10_000, llm_mode="auto", started_ts="t",
            started_monotonic=0.0, anchors=dict(ANCHORS)),
        runner=runner, face=llm_faces.face_for("auto", runner,
                                               tmp_path / "ev"),
        clock=FakeClock(), sleep_fn=lambda _s: None)
    checkpoints._run_verifier_act(ctx2, "C-006", set(), {"acts": []})
    row = _rows(ctx.ws)[0]
    assert row["o"]["status"] == "BLOCKED"
    assert row["r_settle"] == 0.0
    assert "absorbed_from_disk" not in row["o"]


# ------------------------- 5. the field shape: killed after writing ----

def test_go_arx_round2_shape_settles_the_claim(ctx):
    """The measured loss, reconstructed: the verifier wrote its verdict
    (verified) well before the cap, then the kill cut the wrap-up — the
    claim settles from the face the act itself wrote, never as a bare
    kill."""
    (Path(ctx.ws) / "runs" / "verification-C-002.md").write_text(
        "---\n"
        "verdict: verified\n"
        "claim: C-002\n"
        "agent: kunglao-verifier\n"
        "verification_mode: replay_probe\n"
        "artifact: evidence/replay-C-002.json\n"
        "matched_pairs: 15\n"
        "total_pairs: 15\n"
        "min_pair_ratio: 1.0\n"
        "---\n\n"
        "# C-002 verification — independent replay probe\n\n"
        "Fresh-mint controlled comparison: PASS 15/15 byte-exact.\n",
        encoding="utf-8")
    checkpoints._run_verifier_act(ctx, "C-002", set(), {"acts": []})
    row = _rows(ctx.ws)[0]
    assert row["dispatch_id"] == "C-002"
    assert row["o"]["status"] == "TIMEOUT"
    assert row["o"]["absorbed_from_disk"] is True
    assert row["r_settle"] == 1.0


# ------------------------------------ 6. the ledger face owns the marker

def test_ledger_absorb_marker_is_additive_and_default_off(tmp_path):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    ir.record_launch(ws, "C-7", "verify", action_type="verify",
                     variant="verify")
    row = ir.append_transition(ws, "C-7", "TIMEOUT", status="verify",
                               r_settle=1.0, action_type="verify",
                               variant="verify", absorbed_from_disk=True)
    assert row["o"]["absorbed_from_disk"] is True
    assert row["o"]["status"] == "TIMEOUT"   # kill marker rides unchanged
    # default stays byte-identical with the pre-absorb contract
    ir.record_launch(ws, "C-8", "verify", action_type="verify",
                     variant="verify")
    row2 = ir.append_transition(ws, "C-8", "TIMEOUT", status="verify",
                                r_settle=0.0, action_type="verify",
                                variant="verify")
    assert row2["o"] == {"status": "TIMEOUT", "class": "verify",
                         "facts": 0, "variant": "verify"}


def test_ledger_absorbable_verdict_set_is_exact():
    # the absorb gate accepts only the words the ledger can settle
    assert checkpoints._on_disk_verdict_word("verified") == "verified"
    assert checkpoints._on_disk_verdict_word("Confirmed") == "confirmed"
    assert checkpoints._on_disk_verdict_word("REFUTED") == "refuted"
    assert checkpoints._on_disk_verdict_word("pending") == ""
    assert checkpoints._on_disk_verdict_word("") == ""
    assert checkpoints._on_disk_verdict_word("UNVERIFIED-WITH-GAP") == ""
