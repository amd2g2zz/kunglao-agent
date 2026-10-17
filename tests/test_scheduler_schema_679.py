# -*- coding: utf-8 -*-
"""tests/test_scheduler_schema_679.py — issue #679 scheduled_tasks.json schema war.

Why: loop_scheduler._read_entries only recognized the ``jobs`` key or a bare
array. The harness writes ``{"tasks": [...]}`` — a valid, structurally-known
shape it silently classified as "unrecognized": the content was backed up to
*.unrecognized-* and treated as EMPTY, then _write_file rebuilt the file as
{"jobs": [...]}. Live evidence: .claude/scheduled_tasks.json = {"tasks": []}
with kunglao entries stranded in .unrecognized-* sidecars — the harness's
tasks key destroyed on every kunglao upsert, kunglao's own entries exiled.

RED contracts (TDD phase 1):
  1. test_tasks_and_jobs_shapes_coexist — BOTH wrapper keys are recognized
     reads; a document carrying both keys keeps tasks as foreign data while
     kunglao upserts into its own container.
  2. test_foreign_keys_preserved_on_write — unknown sibling keys (schemaVersion,
     owner, ...) survive a kunglao upsert IN THE MAIN FILE, not just a sidecar.
  3. test_harness_record_survives_kunglao_upsert — after upsert the harness's
     record is byte-identical, the shape stays {"tasks": ...}, no
     *.unrecognized-* sidecar (the shape is recognized now), ours added once.
  4. test_tasks_array_byte_identical_after_upsert — negative control: the
     harness tasks array rides an upsert round-trip byte-for-byte.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import loop_scheduler as ls  # noqa: E402

HARNESS_REC = {
    "id": "harness-daily",
    "name": "harness task",
    "cron": "0 9 * * *",
    "prompt": "harness body",
}


def _mk_ws(tmp_path: Path, name: str = "ws") -> Path:
    ws = tmp_path / name
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def _seed(ws: Path, payload: dict) -> Path:
    """Seed scheduled_tasks.json in the SAME wire format the writer emits
    (indent=2, ensure_ascii=False) so byte-level assertions are meaningful."""
    sched = ls.scheduled_tasks_path(ws)
    sched.parent.mkdir(parents=True, exist_ok=True)
    sched.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    return sched


def _ids(entries: list[dict]) -> list:
    return [e.get("id") for e in entries]


class TestBothShapesRecognized:
    def test_tasks_and_jobs_shapes_coexist(self, tmp_path):
        # -- {"tasks": [...]} (harness shape) is a RECOGNIZED read
        ws_t = _mk_ws(tmp_path, "ws-tasks")
        sched_t = _seed(ws_t, {"tasks": [dict(HARNESS_REC)]})
        entries_t, backup_t = ls._read_entries(sched_t)
        assert backup_t is None, "tasks shape must not be 'unrecognized'"
        assert _ids(entries_t) == ["harness-daily"]

        # -- {"jobs": [...]} (kunglao shape) still recognized
        ws_j = _mk_ws(tmp_path, "ws-jobs")
        sched_j = _seed(ws_j, {"jobs": [{"id": "foreign", "prompt": "x"}]})
        entries_j, backup_j = ls._read_entries(sched_j)
        assert backup_j is None
        assert _ids(entries_j) == ["foreign"]

        # -- bare array still recognized (legacy shape)
        ws_a = _mk_ws(tmp_path, "ws-array")
        sched_a = ls.scheduled_tasks_path(ws_a)
        sched_a.parent.mkdir(parents=True, exist_ok=True)
        sched_a.write_text(json.dumps([{"id": "plain"}]), encoding="utf-8")
        entries_a, backup_a = ls._read_entries(sched_a)
        assert backup_a is None
        assert _ids(entries_a) == ["plain"]

        # -- ONE document carrying BOTH keys: kunglao owns "jobs", the
        #    harness's "tasks" rides along untouched through an upsert
        ws_b = _mk_ws(tmp_path, "ws-both")
        sched_b = _seed(ws_b, {"tasks": [dict(HARNESS_REC)],
                               "jobs": [{"id": "old-foreign"}]})
        assert ls.upsert_durable_loop(ws_b) == 0
        doc_b = json.loads(sched_b.read_text(encoding="utf-8"))
        assert doc_b["tasks"] == [HARNESS_REC], (
            "tasks must be foreign data kunglao never rewrites")
        jobs_ids = _ids(doc_b["jobs"])
        assert "old-foreign" in jobs_ids
        assert jobs_ids.count(ls.JOB_ID) == 1


class TestForeignKeysSurviveWrite:
    def test_foreign_keys_preserved_on_write(self, tmp_path):
        # -- jobs container + sibling keys
        ws_1 = _mk_ws(tmp_path, "ws-jobs-sib")
        sched_1 = _seed(ws_1, {"schemaVersion": 9,
                               "jobs": [{"id": "foreign", "prompt": "x"}]})
        assert ls.upsert_durable_loop(ws_1) == 0
        doc_1 = json.loads(sched_1.read_text(encoding="utf-8"))
        assert doc_1.get("schemaVersion") == 9, (
            "unknown sibling keys must survive in the MAIN file")
        ids_1 = _ids(doc_1["jobs"])
        assert "foreign" in ids_1 and ids_1.count(ls.JOB_ID) == 1

        # -- tasks container + sibling keys (harness metadata)
        ws_2 = _mk_ws(tmp_path, "ws-tasks-sib")
        sched_2 = _seed(ws_2, {"owner": "claude-harness",
                               "tasks": [dict(HARNESS_REC)]})
        assert ls.upsert_durable_loop(ws_2) == 0
        doc_2 = json.loads(sched_2.read_text(encoding="utf-8"))
        assert doc_2.get("owner") == "claude-harness"
        ids_2 = _ids(doc_2["tasks"])
        assert "harness-daily" in ids_2 and ids_2.count(ls.JOB_ID) == 1


class TestHarnessRecordSurvives:
    def test_harness_record_survives_kunglao_upsert(self, tmp_path):
        ws = _mk_ws(tmp_path)
        sched = _seed(ws, {"tasks": [dict(HARNESS_REC)]})
        assert ls.upsert_durable_loop(ws) == 0
        doc = json.loads(sched.read_text(encoding="utf-8"))
        assert set(doc) == {"tasks"}, (
            "upsert must keep the tasks container, not rebuild a jobs file")
        ids = _ids(doc["tasks"])
        assert ids.count(ls.JOB_ID) == 1
        assert ids.count("harness-daily") == 1
        # the harness record itself is untouched
        harness = [e for e in doc["tasks"] if e.get("id") == "harness-daily"]
        assert json.dumps(harness[0], ensure_ascii=False) == \
            json.dumps(HARNESS_REC, ensure_ascii=False)
        # RECOGNIZED shape: no sidecar quarantine of kunglao's own entry
        assert not list(sched.parent.glob("*.unrecognized-*")), (
            "a tasks-shaped file must not be exiled to .unrecognized-*")
        assert not list(sched.parent.glob("*.corrupt-*"))
        # ours is discoverable from the tasks container
        assert ls.loop_entry_exists(ws) is True
        # idempotent: a second upsert neither duplicates ours nor the harness record
        assert ls.upsert_durable_loop(ws) == 0
        doc2 = json.loads(sched.read_text(encoding="utf-8"))
        ids2 = _ids(doc2["tasks"])
        assert ids2.count(ls.JOB_ID) == 1
        assert ids2.count("harness-daily") == 1


class TestNegativeControl:
    def test_tasks_array_byte_identical_after_upsert(self, tmp_path):
        """T4 negative control: {"tasks":[...]} through a full upsert — every
        harness record's exact serialized bytes (indentation included) still
        appear in the rewritten file, in order."""
        ws = _mk_ws(tmp_path)
        records = [dict(HARNESS_REC),
                   {"id": "second", "prompt": "p2", "cron": "*/15 * * * *"}]
        sched = _seed(ws, {"tasks": records})
        assert ls.upsert_durable_loop(ws) == 0
        after = sched.read_text(encoding="utf-8")
        for rec in records:
            blob = _indented(rec)
            assert blob in after, f"harness record mutated: {rec['id']!r}"
        doc = json.loads(after)
        harness_slice = [e for e in doc["tasks"] if e.get("id") != ls.JOB_ID]
        assert json.dumps(harness_slice, ensure_ascii=False) == \
            json.dumps(records, ensure_ascii=False)
        # ours appended, harness first — original order preserved
        assert _ids(doc["tasks"]) == ["harness-daily", "second", ls.JOB_ID]


def _indented(rec: dict) -> str:
    """Serialize rec exactly as it sits inside the file (indent=2 at the
    tasks-element level = 4-space prefix)."""
    blob = json.dumps(rec, ensure_ascii=False, indent=2)
    return "\n".join("    " + line for line in blob.split("\n"))
