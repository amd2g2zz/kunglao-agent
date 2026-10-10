# -*- coding: utf-8 -*-
"""tests/test_verdict_face_513.py — issue 513 contract (TDD).

Field evidence (combat wt1, zero-intervention): the verdict act's prompt
was one bare line, ran cwd=repo (not the workspace), carried no schema
and no tool permission — it produced no evidence/verdict.json and the
run terminated BLOCKED verdict-missing despite all claims PROVEN.
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
def ctx(tmp_path):
    stub_repo = _stub_repo(tmp_path)
    ws = tmp_path / "ws"
    ev = tmp_path / "ev"
    (ws / "facts").mkdir(parents=True)
    (ws / "runs").mkdir()
    (ws / "facts" / "_INDEX.md").write_text(
        "# _INDEX\nF002 | PROVEN | C-004 | params | done\n",
        encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        "claims:\n"
        "  - id: C-004\n    status: PROVEN\n    question: q1\n"
        "    answers_question: pq-1\n"
        "  - id: C-005\n    status: PROVEN\n    question: q2\n"
        "    answers_question: pq-2\n", encoding="utf-8")
    (ws / "task_spec.yaml").write_text(
        "primary_questions:\n- id: pq-1\n  question: q1\n"
        "- id: pq-2\n  question: q2\n", encoding="utf-8")
    state = model.RunState(
        run_id="v1", unit="py-derive-v1", family="smoke",
        repo=str(stub_repo),
        task_dir=str(stub_repo / "eval/v1/tasks/smoke/py-derive-v1"),
        ws=str(ws), evidence_dir=str(ev), budget_seconds=10_000,
        llm_mode="auto", started_ts="t", started_monotonic=0.0,
        anchors=dict(ANCHORS))
    runner = ScriptedRunner()
    runner.on("claude", "-p", rc=0, stdout='{"result": "done"}')
    yield checkpoints.RunContext(
        state=state, runner=runner,
        face=llm_faces.face_for("auto", runner, ev),
        clock=FakeClock(), sleep_fn=lambda _s: None)


def test_verdict_prompt_carries_the_full_contract(ctx):
    """The act's prompt must name: the workspace path, every input file,
    the schema-v11 field skeleton, and the output path."""
    checkpoints._verdict_face(ctx, {"acts": []}, 5)
    calls = " ".join(ctx.runner.calls)
    assert str(ctx.ws) in calls, "workspace path not named"
    for needle in ("task_spec.yaml", "claim-register.yaml",
                   "_INDEX.md", "verdict.json"):
        assert needle in calls, f"prompt missing {needle}"
    for field in ("primary_questions", "unresolved", "contradictions"):
        assert field in calls, f"prompt missing schema field {field}"


def test_verdict_act_runs_in_the_workspace(ctx):
    """cwd must be the workspace (the old face ran it in the repo —
    the act could not even see its inputs)."""
    checkpoints._verdict_face(ctx, {"acts": []}, 5)
    # ScriptedRunner records cwd per call: patch capture via subclass
    seen = {}

    class Spy(ScriptedRunner):
        def run(self, cmd, cwd=None, timeout=None):
            seen["cwd"] = str(cwd)
            return model.CmdOutcome(rc=0, stdout='{"result": "done"}',
                                    stderr="")

    ctx.runner = Spy()
    ctx.face = llm_faces.face_for("auto", ctx.runner,
                                  Path(ctx.state.evidence_dir))
    checkpoints._verdict_face(ctx, {"acts": []}, 5)
    assert seen.get("cwd") == str(ctx.ws), seen.get("cwd")


def test_verdict_act_has_write_permission(ctx):
    """--allowedTools must include Write (a bare -p has no file tools)."""
    checkpoints._verdict_face(ctx, {"acts": []}, 5)
    assert any("--allowedTools" in c and "Write" in c
               for c in ctx.runner.calls)
