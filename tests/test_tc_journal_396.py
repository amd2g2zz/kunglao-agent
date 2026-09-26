# -*- coding: utf-8 -*-
"""tests/test_tc_journal_396.py — per-dispatch tool-call journal (issue 396).

Pins the cheapest recording face: one JSONL line per tool call
(tool name, args hash, return status, files touched, ts), written by a
RETURN-TIME aggregation (worker exit / loop runner) — never inside tool
dispatch. Includes the derivation face from the existing kunglao_log day files
tool_call events (no new instrumentation) and its idempotence at any
wall-clock distance. All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import kunglao_log  # noqa: E402
import tc_journal  # noqa: E402


def _read_journal(ws: Path) -> list[dict]:
    p = ws / "runs" / "tc-journal.jsonl"
    if not p.is_file():
        return []
    return [json.loads(ln) for ln in
            p.read_text(encoding="utf-8").splitlines() if ln.strip()]


class TestRecordCall:
    def test_one_jsonl_line_per_call_schema(self, tmp_path):
        ok = tc_journal.record_call(
            tmp_path, dispatch_id="C-7", tool="Bash",
            args_hash="a" * 64, status=0,
            files=["facts/F001.md"], ts="2026-09-27T00:00:00Z",
            actor="worker:kunglao-worker")
        assert ok is True
        rows = _read_journal(tmp_path)
        assert len(rows) == 1
        row = rows[0]
        assert row["schema"] == "tc-journal/1"
        assert row["dispatch_id"] == "C-7"
        assert row["tool"] == "Bash"
        assert row["args_sha256"] == "a" * 64
        assert row["status"] == 0
        assert row["files"] == ["facts/F001.md"]
        assert row["ts"] == "2026-09-27T00:00:00Z"
        assert row["actor"] == "worker:kunglao-worker"

    def test_optional_fields_explicit_nulls(self, tmp_path):
        tc_journal.record_call(tmp_path, dispatch_id="C-1", tool="Read",
                               ts="2026-09-27T00:00:01Z")
        row = _read_journal(tmp_path)[0]
        assert row["args_sha256"] is None
        assert row["status"] is None
        assert row["files"] == []
        assert row["actor"] is None

    def test_files_normalized_to_list(self, tmp_path):
        tc_journal.record_call(tmp_path, dispatch_id="C-1", tool="Write",
                               files="runs/deliverables/candidate.py",
                               ts="2026-09-27T00:00:02Z")
        assert _read_journal(tmp_path)[0]["files"] == \
            ["runs/deliverables/candidate.py"]

    def test_never_raises_on_bad_input(self, tmp_path):
        assert tc_journal.record_call(
            tmp_path, dispatch_id="C-1", tool="Bash",
            files=object()) is False  # unserializable -> fail-open False

    def test_missing_dirs_created(self, tmp_path):
        assert tc_journal.record_call(
            tmp_path, dispatch_id="C-1", tool="Bash",
            ts="2026-09-27T00:00:00Z") is True


class TestRecordCalls:
    def test_batch_appends_in_order(self, tmp_path):
        n = tc_journal.record_calls(tmp_path, "C-3", [
            {"tool": "Bash", "args_hash": "b" * 64, "status": 0},
            {"tool": "Read", "status": 1, "files": ["task_spec.yaml"]},
        ], ts="2026-09-27T00:00:03Z")
        assert n == 2
        rows = _read_journal(tmp_path)
        assert [r["tool"] for r in rows] == ["Bash", "Read"]
        assert rows[1]["dispatch_id"] == "C-3"


def _seed_logs(ws: Path) -> None:
    """Real kunglao_log.emit rows: two tool_call events + one non-tool row."""
    kunglao_log.emit(ws, actor="worker:kunglao-worker", action="tool_call",
                     claim="C-9", tool="Bash", artifact="facts/F001.md",
                     exit=0, detail="sha256sum")
    kunglao_log.emit(ws, actor="worker:kunglao-worker", action="tool_call",
                     claim="C-9", tool="Read", exit=None)
    kunglao_log.emit(ws, actor="worker:kunglao-worker", action="dispatch",
                     claim="C-9", detail="allow")


class TestFromKunglaoLog:
    def test_derivation_from_existing_tool_call_rows(self, tmp_path):
        _seed_logs(tmp_path)
        rows = tc_journal.from_kunglao_log(tmp_path)
        assert len(rows) == 2
        by_tool = {r["tool"]: r for r in rows}
        bash = by_tool["Bash"]
        assert bash["dispatch_id"] == "C-9"
        assert bash["files"] == ["facts/F001.md"]
        assert bash["status"] == 0
        # the log schema carries no args: honest documented absence
        assert bash["args_sha256"] is None
        assert bash["ts"]
        assert by_tool["Read"]["files"] == []

    def test_unattributed_calls_marked(self, tmp_path):
        kunglao_log.emit(ws=tmp_path, actor="hook:x", action="tool_call",
                         tool="Bash", exit=0)
        rows = tc_journal.from_kunglao_log(tmp_path)
        assert rows[0]["dispatch_id"] == "unattributed"

    def test_no_logs_empty(self, tmp_path):
        assert tc_journal.from_kunglao_log(tmp_path) == []


class TestHarvestFromLog:
    def test_harvest_appends_and_is_idempotent(self, tmp_path):
        _seed_logs(tmp_path)
        n1 = tc_journal.harvest_from_log(tmp_path)
        assert n1 == 2
        # re-run at any wall-clock distance: dedupe holds, zero churn
        n2 = tc_journal.harvest_from_log(tmp_path)
        assert n2 == 0
        assert len(_read_journal(tmp_path)) == 2

    def test_harvest_grows_with_new_log_rows(self, tmp_path):
        _seed_logs(tmp_path)
        tc_journal.harvest_from_log(tmp_path)
        kunglao_log.emit(tmp_path, actor="worker:kunglao-worker",
                         action="tool_call", claim="C-9", tool="Grep",
                         exit=0)
        assert tc_journal.harvest_from_log(tmp_path) == 1
        assert len(_read_journal(tmp_path)) == 3

    def test_direct_calls_survive_harvest(self, tmp_path):
        """record_call rows and derived rows coexist; identity dedupe never
        drops a direct record_call even with identical tool/ts."""
        tc_journal.record_call(tmp_path, dispatch_id="C-1", tool="Bash",
                               args_hash="c" * 64, status=0,
                               ts="2026-09-27T00:00:00Z")
        assert tc_journal.harvest_from_log(tmp_path) == 0
        assert len(_read_journal(tmp_path)) == 1

    def test_empty_workspace_zero(self, tmp_path):
        assert tc_journal.harvest_from_log(tmp_path) == 0
