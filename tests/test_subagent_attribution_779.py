# -*- coding: utf-8 -*-
"""tests/test_subagent_attribution_779.py — the worker-attribution fix
(issue #779 face one, probe verdict (a)).

The probe (docs/architecture/subagent-hook-probe.md) proved the
inheritance gap precisely: on CLI 2.1.270 Task-spawned tool calls FIRE
the workspace PreToolUse/PostToolUse hooks but carry the PARENT
session_id, with the worker identity riding agent_id/agent_type. The
fix makes the observation faces agent-aware:

  - step-record/1 rows carry agent_id/agent_type when the payload has
    them (no key drift on parent rows);
  - aggregation scopes by agent, and the parent bucket EXCLUDES
    agent-tagged rows (no double-counting across stops);
  - the round-closure settle threads the SubagentStop agent_id, so a
    worker step's completion grain aggregates ITS OWN tool calls.

All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
HOOKS = ROOT / "hooks"
for p in (str(ROOT), str(SCRIPTS), str(HOOKS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from rlvr import step_grain as sg  # noqa: E402
from rlvr import step_ledger as sl  # noqa: E402

from _factories import write_claims_register  # noqa: E402

TS = "2026-10-19T00:00:00Z"


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    write_claims_register(ws, [{"id": "C-5", "status": "OPEN"}])
    return ws


def _agent_row(ws: Path, session: str, agent: str | None, n: int) -> list[str]:
    """n hash-only step-record/1 rows for one (session, agent) pair."""
    ids = []
    for i in range(n):
        kw = {"agent_id": agent, "agent_type": "kunglao-worker"} \
            if agent else {}
        row = sl.build_step_row(
            session_id=session, tool="Bash",
            tool_input={"command": f"step-{session}-{agent}-{i}"},
            tool_response={"stdout": "x"}, ts=TS, **kw)
        assert sl.record_step(ws, row) is not None
        ids.append(row["call_id"])
    return ids


# ============== 1. agent attribution (the #779 verdict-(a) fix) ==========

class TestAgentAttribution:
    def test_step_row_carries_agent_identity(self):
        row = sl.build_step_row(session_id="sess-9", tool="Bash",
                                tool_input={"command": "x"},
                                tool_response={}, ts=TS,
                                agent_id="agent-a", agent_type="worker")
        assert row["agent_id"] == "agent-a"
        assert row["agent_type"] == "worker"

    def test_parent_row_has_no_agent_keys(self):
        row = sl.build_step_row(session_id="sess-9", tool="Bash",
                                tool_input={"command": "x"},
                                tool_response={}, ts=TS)
        assert "agent_id" not in row and "agent_type" not in row, (
            "no key drift on parent rows — the additive whitelist only "
            "grows keys when an agent identity exists")

    def test_record_step_preserves_agent_identity(self, tmp_path):
        ws = _ws(tmp_path)
        row = sl.build_step_row(session_id="s", tool="Bash",
                                tool_input={}, tool_response={}, ts=TS,
                                agent_id="agent-a", agent_type="worker")
        assert sl.record_step(ws, row) is not None
        got = [r for r in sl.read_steps(ws) if r.get("agent_id")]
        assert len(got) == 1 and got[0]["agent_id"] == "agent-a"

    def test_aggregate_scopes_by_agent(self, tmp_path):
        ws = _ws(tmp_path)
        _agent_row(ws, "sess-9", "agent-a", 2)
        _agent_row(ws, "sess-9", "agent-b", 3)
        _agent_row(ws, "sess-9", None, 1)
        agg = sg.aggregate_session_steps(ws, "sess-9", agent_id="agent-a")
        assert agg["tool_calls"] == 2, "only that agent's rows aggregate"
        agg_b = sg.aggregate_session_steps(ws, "sess-9", agent_id="agent-b")
        assert agg_b["tool_calls"] == 3
        parent = sg.aggregate_session_steps(ws, "sess-9", agent_id=None)
        assert parent["tool_calls"] == 1, ("the parent bucket excludes "
                                           "agent-tagged rows (no "
                                           "double-counting across stops)")

    def test_settle_scopes_the_grain_to_the_agent(self, tmp_path):
        ws = _ws(tmp_path)
        from rlvr import incremental_reward as ir
        ir.record_launch(ws, "C-5", "dispatch")
        _agent_row(ws, "sess-9", "agent-a", 2)
        _agent_row(ws, "sess-9", None, 5)
        row = sg.settle_step(ws, "sess-9", agent_id="agent-a")
        assert row is not None
        assert row["agent_id"] == "agent-a"
        assert row["tool_calls"] == 2, ("the worker step's aggregate is "
                                        "the worker's own tool calls, not "
                                        "the whole session's")

    def test_step_id_deterministic_in_session_agent_ordinal(self, tmp_path):
        a1 = sg.step_id_for("sess-9", 0, agent_id="agent-a")
        a1_again = sg.step_id_for("sess-9", 0, agent_id="agent-a")
        b1 = sg.step_id_for("sess-9", 0, agent_id="agent-b")
        assert a1 == a1_again and a1 != b1

    def test_capture_hook_records_agent_identity(self, tmp_path):
        import step_record_capture as src
        ws = _ws(tmp_path)
        payload = {"cwd": str(ws), "session_id": "sess-9",
                   "agent_id": "agent-a", "agent_type": "kunglao-worker",
                   "tool_name": "Bash", "tool_input": {"command": "ls"},
                   "tool_response": {"stdout": ""}}
        assert src.process_event(payload) == 0
        rows = sl.read_steps(ws)
        assert rows and rows[-1].get("agent_id") == "agent-a"

    def test_round_closure_threads_the_agent_id(self, tmp_path, capsys):
        import round_closure
        ws = _ws(tmp_path)
        from rlvr import incremental_reward as ir
        ir.record_launch(ws, "C-5", "dispatch")
        _agent_row(ws, "sess-9", "agent-a", 2)
        _agent_row(ws, "sess-9", None, 5)
        rc = round_closure.main_with_payload(
            {"cwd": str(ws), "session_id": "sess-9", "agent_id": "agent-a",
             "agent_type": "kunglao-worker",
             "transcript_path": str(ws / "t.jsonl")})
        capsys.readouterr()
        assert rc == 0
        grains = sl.read_step_grains(ws, "sess-9")
        assert grains and grains[-1]["agent_id"] == "agent-a"
        assert grains[-1]["tool_calls"] == 2

    def test_round_closure_without_agent_keeps_parent_grain(
            self, tmp_path, capsys):
        import round_closure
        ws = _ws(tmp_path)
        _agent_row(ws, "sess-9", None, 3)
        rc = round_closure.main_with_payload(
            {"cwd": str(ws), "session_id": "sess-9",
             "transcript_path": str(ws / "t.jsonl")})
        capsys.readouterr()
        assert rc == 0
        grains = sl.read_step_grains(ws, "sess-9")
        # no pending step -> the non-worker stop settles nothing (the
        # designed posture is unchanged without an agent identity)
        assert grains == []

