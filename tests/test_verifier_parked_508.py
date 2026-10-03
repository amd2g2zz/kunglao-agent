# -*- coding: utf-8 -*-
"""tests/test_verifier_parked_508.py — issue 508 contract (TDD).

Field evidence (round-8B resume): decision=DISPATCH_VERIFIER with only
PARKed claims FAILs at priority_ratio — the probe's own evidence (the
partial facts) is never consumed as the verifier target source. A
partial-bearing claim parked for a verifier IS verifier work.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
TESTS = Path(__file__).resolve().parents[1] / "tests"
for p in (SCRIPTS, TESTS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from e2e import checkpoints, llm_faces, model  # noqa: E402
from test_e2e_runner import ANCHORS, FakeClock, ScriptedRunner  # noqa: E402


def _stub_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    task = repo / "eval/v1/tasks/smoke/py-derive-v1"
    (task / "target").mkdir(parents=True)
    (task / "target/derive.py").write_text("def derive(b):\n    return 1\n",
                                           encoding="utf-8")
    (task / "task.yaml").write_text("schema: kunglao-eval-task/1\n",
                                    encoding="utf-8")
    (repo / "scripts").mkdir()
    return repo


@pytest.fixture()
def ctx(_unused, tmp_path):
    stub_repo = _stub_repo(tmp_path)
    ws = tmp_path / "ws"
    ev = tmp_path / "ev"
    facts = ws / "facts"
    runs = ws / "runs"
    for d in (facts, runs, ev):
        d.mkdir(parents=True)
    # the 8B resume shape: BOTH claims PARKed, workers complete,
    # partial facts awaiting the verifier
    (ws / "claim-register.yaml").write_text(
        "claims:\n"
        "  - id: C-004\n    status: PARK\n    question: q1\n"
        "  - id: C-005\n    status: PARK\n    question: q2\n",
        encoding="utf-8")
    (facts / "_INDEX.md").write_text(
        "# _INDEX\n"
        "F002 | INFERRED | C-004 | sigma candidates | pending\n"
        "F007 | INFERRED | C-005 | reimpl matrix | pending\n",
        encoding="utf-8")
    for fid in ("F002", "F007"):
        (facts / f"{fid}.md").write_text(
            f"---\nid: {fid}\nstatus: INFERRED\nverified: pending\n---\n",
            encoding="utf-8")
    state = model.RunState(
        run_id="b1", unit="py-derive-v1", family="smoke",
        repo=str(stub_repo), task_dir=str(stub_repo / "eval/v1/tasks/smoke/py-derive-v1"),
        ws=str(ws), evidence_dir=str(ev), budget_seconds=10_000,
        llm_mode="auto", started_ts="t", started_monotonic=0.0,
        anchors=dict(ANCHORS))
    runner = ScriptedRunner()
    runner.on("heartbeat_tick", rc=0, stdout="ok")
    runner.on("convergence_check", rc=2,
              stdout='{"decision": "DISPATCH_VERIFIER", "exit_code": 2}')
    runner.on("priority_ratio", rc=0, stdout="[]")  # PARKed -> unranked
    runner.on("claude", "-p", rc=0, stdout='{"result": "done"}')
    yield checkpoints.RunContext(
        state=state, runner=runner,
        face=llm_faces.face_for("auto", runner, ev),
        clock=FakeClock(), sleep_fn=lambda _s: None)


@pytest.fixture(name="_unused")
def _unused_fixture():
    yield None


def test_parked_claims_with_partials_dispatch_verifier(ctx):
    """THE 8B resume shape: the verifier target comes from the partial
    facts' claim column — not the (empty) priority ranking."""
    flow, terminal, _ = checkpoints._loop_one_tick(
        ctx, set(), {"acts": []}, 0, 0)
    assert flow == "continue" and terminal is None, (
        f"resume shape must not FAIL at priority_ratio: {terminal}")
    prompt = Path(ctx.state.evidence_dir) / "dispatch-prompt-V-C-004.md"
    assert prompt.is_file(), "verifier act never dispatched"


def test_park_is_not_a_worker_dispatch_target(ctx):
    """The fix must not make PARKed claims WORKER-dispatchable: a plain
    DISPATCH decision with the same empty ranking still FAILs honestly
    (the ranking itself is untouched)."""
    ctx.runner.rules = [r for r in ctx.runner.rules
                        if "convergence_check" not in r[0]]
    ctx.runner.on("convergence_check", rc=1,
                  stdout='{"decision": "DISPATCH", "exit_code": 1}')
    ctx.runner.on("priority_ratio", rc=0, stdout="[]")
    flow, terminal, _ = checkpoints._loop_one_tick(
        ctx, set(), {"acts": []}, 0, 0)
    assert terminal is not None and terminal.status == "FAIL"
