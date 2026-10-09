#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_rc1_checkpoints_hardening_601.py — RC1 hardening pins for
the checkpoint-side fixes from the #601 audit triage (consolidated
triage, RC1 blockers table).

Fix 2 (audit 4-L4 / 5-F5, with 1-F2's stale-epoch shape) — absorb-at-kill
writer binding: the verify act's on-disk verdict settles a TIMEOUT kill
ONLY when the note carries the CURRENT dispatch's `verify-stamp:` (the
orchestrator mints a fresh token per verify dispatch and injects it into
the act's contract). A stale verdict from a previous attempt and a
foreign-written unstamped file keep the bare kill (byte-identical); a
stamped current-attempt verdict still absorbs (the #597 contract holds).

Fix 4 (audit 4-L1) — censored-timeout credit: a TIMEOUT act's settlement
banks the failure floor (0.0) into the arm posterior, the transition row,
and the store row — no success mass from an unobserved outcome; fact
progress keeps its credit face through Φ (phi_delta / r_incr on the same
row). Observed outcomes keep the #524 continuous credit unchanged.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from e2e import checkpoints, llm_faces, model  # noqa: E402
from rlvr import q_cells  # noqa: E402
from test_e2e_runner import (ANCHORS, DERIVE_PY, FakeClock,  # noqa: E402
                             ScriptedRunner, TASK_YAML)


# ------------------------------------------------------------ fixtures

@pytest.fixture()
def stub_repo(tmp_path):
    """Minimal unit repo (same shape as test_absorb_settle_597's)."""
    repo = tmp_path / "repo"
    task = repo / "eval/v1/tasks/smoke/py-derive-v1"
    (task / "target").mkdir(parents=True)
    (task / "target/derive.py").write_text(DERIVE_PY, encoding="utf-8")
    (task / "task.yaml").write_text(TASK_YAML, encoding="utf-8")
    (repo / "scripts").mkdir()
    return repo


def _make_ctx(stub_repo, tmp_path, runner):
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
    return checkpoints.RunContext(
        state=state, runner=runner,
        face=llm_faces.face_for("auto", runner, ev_dir),
        clock=FakeClock(), sleep_fn=lambda _s: None)


class _ContractKillRunner(ScriptedRunner):
    """The verify act is hard-killed at the act budget cap (rc -1,
    timed_out). `land_note` controls the contract-compliance simulation:
    when truthy, the act copies the dispatch's verify-stamp binding from
    its prompt into the note it writes mid-run (the honest #597 shape
    under the #601 binding); when falsy, the act writes nothing."""

    land_note = False
    verdict = "verified"
    stamp_override = ""   # forged token: land a WRONG stamp

    def run(self, cmd, cwd=None, timeout=None):
        argv = " ".join(str(c) for c in cmd)
        if "-p" in argv and "VERIFIER contract" in argv:
            self.calls.append(argv)
            if self.land_note:
                self._land(argv, cwd)
            return model.CmdOutcome(rc=-1, stdout="",
                                    stderr="TIMEOUT after 1800s",
                                    timed_out=True)
        return super().run(cmd, cwd=cwd, timeout=timeout)

    def _land(self, argv, cwd) -> None:
        m_stamp = re.search(r"verify-stamp:\s*(\S+)", argv)
        m_claim = re.search(r"^claim:\s*(\S+)", argv, re.M)
        token = self.stamp_override or (m_stamp.group(1) if m_stamp else "")
        token = token.strip("`\"'")   # copy the token value, not the wraps
        lines = ["---"]
        if m_claim:
            lines.append(f"claim: {m_claim.group(1)}")
        lines += [f"verdict: {self.verdict}"]
        if token:
            lines.append(f"verify-stamp: {token}")
        lines += ["verification_mode: replay_probe", "---", "",
                  "replay face"]
        (Path(cwd) / "runs" /
         f"verification-{m_claim.group(1) if m_claim else 'C-0'}.md"
         ).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _rows(ws: Path) -> list[dict]:
    p = Path(ws) / "runs" / "transitions.jsonl"
    if not p.is_file():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8")
            .splitlines() if l.strip()]


# ================================================================ Fix 2
# ==================================== absorb-at-kill writer binding ====

def test_stamped_current_attempt_verdict_still_absorbs(stub_repo,
                                                       tmp_path):
    """The #597 contract holds: the act landed its stamped verdict
    mid-run, then the cap cut the wrap-up — the verdict settles."""
    runner = _ContractKillRunner()
    runner.land_note = True
    runner.verdict = "verified"
    ctx = _make_ctx(stub_repo, tmp_path, runner)
    checkpoints._run_verifier_act(ctx, "C-002", set(), {"acts": []})
    rows = _rows(ctx.ws)
    assert len(rows) == 1
    row = rows[0]
    assert row["o"]["status"] == "TIMEOUT"          # kill marker retained
    assert row["o"]["absorbed_from_disk"] is True   # absorb marker present
    assert row["r_settle"] == 1.0                   # credit per the mapping


def test_dispatch_prompt_carries_the_fresh_stamp(stub_repo, tmp_path):
    """The binding is deliverable: every verify dispatch's contract
    embeds a minted `verify-stamp:` token, fresh per dispatch."""
    runner = _ContractKillRunner()
    ctx = _make_ctx(stub_repo, tmp_path, runner)
    checkpoints._run_verifier_act(ctx, "C-002", set(), {"acts": []})
    prompt = (Path(ctx.state.evidence_dir)
              / "dispatch-prompt-V-C-002.md").read_text(encoding="utf-8")
    m = re.search(r"verify-stamp:\s*(\S+)", prompt)
    assert m is not None, "the contract must carry the stamp token"
    assert m.group(1).startswith("vs-"), "minted token shape"
    checkpoints._run_verifier_act(ctx, "C-002", set(), {"acts": []})
    prompt2 = (Path(ctx.state.evidence_dir)
               / "dispatch-prompt-V-C-002.md").read_text(encoding="utf-8")
    m2 = re.search(r"verify-stamp:\s*(\S+)", prompt2)
    assert m2.group(1) != m.group(1), "a re-dispatch mints a fresh stamp"


def test_unstamped_foreign_file_keeps_the_bare_kill(stub_repo, tmp_path):
    """4-L4/5-F5 trigger (a): a worker-forged `runs/verification-*.md`
    pre-written BEFORE the dispatch carries no stamp — the killed act's
    settle stays the bare kill, byte-identical."""
    runner = _ContractKillRunner()   # writes nothing
    ctx = _make_ctx(stub_repo, tmp_path, runner)
    (ctx.ws / "runs" / "verification-C-003.md").write_text(
        "---\nclaim: C-003\nverdict: verified\n"
        "verification_mode: replay_probe\n---\n\nforged replay face\n",
        encoding="utf-8")
    checkpoints._run_verifier_act(ctx, "C-003", set(), {"acts": []})
    rows = _rows(ctx.ws)
    assert len(rows) == 1
    row = rows[0]
    assert row["o"]["status"] == "TIMEOUT"
    assert row["r_settle"] == 0.0
    assert "absorbed_from_disk" not in row["o"]
    assert set(row) == {"ts", "dispatch_id", "action_type", "s", "a",
                        "o", "s_prime_phi", "phi_before", "r_incr",
                        "r_settle", "done"}


def test_mismatched_stamp_keeps_the_bare_kill(stub_repo, tmp_path):
    """A note carrying SOMEONE ELSE's stamp token (a forged guess, a
    previous act's token replayed) does not settle this dispatch."""
    runner = _ContractKillRunner()
    runner.land_note = True
    runner.stamp_override = "vs-" + "0" * 16   # wrong token
    ctx = _make_ctx(stub_repo, tmp_path, runner)
    checkpoints._run_verifier_act(ctx, "C-004", set(), {"acts": []})
    row = _rows(ctx.ws)[0]
    assert row["r_settle"] == 0.0
    assert "absorbed_from_disk" not in row["o"]


def test_stale_verdict_from_previous_attempt_never_absorbs(stub_repo,
                                                           tmp_path):
    """1-F2's stale-epoch shape: attempt 1 lands its stamped verdict and
    is killed (absorbs); the claim is re-dispatched, attempt 2 is killed
    WITHOUT the act writing anything — attempt-1's stale note on disk
    must NOT bank attempt-2's kill."""
    runner = _ContractKillRunner()
    runner.land_note = True          # attempt 1: contract-compliant
    runner.verdict = "verified"
    ctx = _make_ctx(stub_repo, tmp_path, runner)
    checkpoints._run_verifier_act(ctx, "C-005", set(), {"acts": []})
    first = _rows(ctx.ws)[0]
    assert first["o"]["absorbed_from_disk"] is True
    assert first["r_settle"] == 1.0
    runner.land_note = False         # attempt 2: writes nothing
    checkpoints._run_verifier_act(ctx, "C-005", set(), {"acts": []})
    rows = _rows(ctx.ws)
    assert len(rows) == 2
    second = rows[1]
    assert second["o"]["status"] == "TIMEOUT"
    assert second["r_settle"] == 0.0
    assert "absorbed_from_disk" not in second["o"]


# ================================================================ Fix 4
# ======================================== censored-timeout credit =====

def _credit_ctx(stub_repo, tmp_path):
    """Workspace + ctx shaped for _launch_dispatch/_land_dispatch (the
    test_rlvr_p0_524 fixture shape)."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "facts").mkdir()
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-004\n  status: OPEN\n"
        "- id: C-005\n  status: OPEN\n", encoding="utf-8")
    state = model.RunState(
        run_id="r", unit="u", family="release", repo=str(stub_repo),
        task_dir=str(stub_repo), ws=str(ws),
        evidence_dir=str(tmp_path / "ev"), budget_seconds=10,
        llm_mode="dry", started_ts="t", started_monotonic=0.0,
        anchors={"goal_verbatim": "g", "success_criterion": "s",
                 "verification_method": "reproduction"},
        method_family="static-decompile")

    class _Face:
        def launch_dispatch(self, request):
            return "h"

    return checkpoints.RunContext(state=state, runner=object(),
                                  face=_Face(), clock=object(),
                                  sleep_fn=lambda _s: None)


def _two_verified_facts(ws: Path, claim: str, start: int = 1) -> None:
    """Two fact files that both cite the claim AND carry terminal
    status — they move the Φ fact face (the progress credit face)."""
    for i in (start, start + 1):
        (ws / "facts" / f"F{i:03d}.md").write_text(
            f"---\nclaim_id: {claim}\nstatus: VERIFIED\n---\nbody\n",
            encoding="utf-8")


def test_timeout_with_facts_banks_failure_floor_only(stub_repo, tmp_path):
    """4-L1: a TIMEOUT with 2 cited facts banks 0.0 — no success mass
    from an unobserved outcome — into the posterior row, the transition
    row, and the store row; the audit keeps the censored marker."""
    ctx = _credit_ctx(stub_repo, tmp_path)
    d2 = set()
    checkpoints._launch_dispatch(ctx, "C-005", d2)
    _two_verified_facts(ctx.ws, "C-005")   # facts land mid-act
    checkpoints._land_dispatch(ctx, "C-005",
                               llm_faces.ActRecord(
                                   claim="C-005", mode="auto",
                                   outcome="TIMEOUT", detail={}),
                               d2, {"acts": []})
    # arm posterior: the failure floor — success mass stays out
    settled = [r for r in q_cells.JSONLQStore(str(ctx.ws)).observations()
               if r.get("credit") is not None and r.get("claim") == "C-005"]
    assert settled and settled[-1]["credit"] == 0.0
    # transition row: the settlement value is the floor; facts stay
    # recorded and the row keeps the TIMEOUT status
    trow = [r for r in _rows(Path(str(ctx.ws)))
            if r.get("dispatch_id") == "C-005"]
    assert trow and trow[-1]["r_settle"] == 0.0
    assert trow[-1]["o"]["facts"] == 2
    assert trow[-1]["o"]["status"] == "TIMEOUT"
    # the audit event keeps the censoring visible
    aud = []
    for p2 in sorted((ctx.ws / "runs" / "logs").glob("*.jsonl")):
        for l in p2.read_text().splitlines():
            if "posterior_updated" not in l:
                continue
            e = json.loads(l)
            d = e.get("detail")
            if isinstance(d, str):
                try:
                    d = json.loads(d)
                except ValueError:
                    d = {}
            e["detail"] = d
            aud.append(e)
    assert aud and aud[-1]["detail"]["counts"].get("censored") is True
    assert aud[-1]["detail"]["counts"].get("credit") == 0.0


def test_timeout_with_facts_still_moves_the_progress_face(stub_repo,
                                                          tmp_path):
    """4-L1's credit split: the timed-out act's facts keep their
    progress credit through Φ — the row's Φ moved and r_incr is
    positive — the facts never ride the settlement value again."""
    ctx = _credit_ctx(stub_repo, tmp_path)
    d2 = set()
    checkpoints._launch_dispatch(ctx, "C-005", d2)
    _two_verified_facts(ctx.ws, "C-005")   # facts land mid-act
    checkpoints._land_dispatch(ctx, "C-005",
                               llm_faces.ActRecord(
                                   claim="C-005", mode="auto",
                                   outcome="TIMEOUT", detail={}),
                               d2, {"acts": []})
    trow = [r for r in _rows(Path(str(ctx.ws)))
            if r.get("dispatch_id") == "C-005"][-1]
    assert trow["s_prime_phi"] > trow["phi_before"], \
        "facts bank progress through Φ"
    assert trow["r_incr"] > 0, "the Φ movement survives the cost term"


def test_observed_error_with_facts_keeps_continuous_credit(stub_repo,
                                                           tmp_path):
    """Scope guard: only the censored class changes. An OBSERVED
    failure (ERROR) with 2 cited facts keeps the #524 hindsight
    partial credit (0.5)."""
    ctx = _credit_ctx(stub_repo, tmp_path)
    d2 = set()
    checkpoints._launch_dispatch(ctx, "C-005", d2)
    _two_verified_facts(ctx.ws, "C-005")   # facts land mid-act
    checkpoints._land_dispatch(ctx, "C-005",
                               llm_faces.ActRecord(
                                   claim="C-005", mode="auto",
                                   outcome="ERROR", detail={}),
                               d2, {"acts": []})
    settled = [r for r in q_cells.JSONLQStore(str(ctx.ws)).observations()
               if r.get("credit") is not None and r.get("claim") == "C-005"]
    assert settled and settled[-1]["credit"] == 0.5


