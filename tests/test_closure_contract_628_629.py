# -*- coding: utf-8 -*-
"""tests/test_closure_contract_628_629.py — #628+#629: the closure chain must
be wired end-to-end and honest.

#628 (adjudicated: pending queue + 完工门): run_rollup Step 2.5 writes
runs/notes-due.yaml when a terminal claim lacks a notes/ file; the Stop-face
completion gate refuses completion while notes are due. Fail-open when the
queue is absent. Judge-then-revise doctrine preserved: nothing auto-WRITES the
note — the queue only makes the obligation impossible to forget.

#629 (adjudicated: feedback step 10 in the tick): heartbeat_tick runs
feedback.check_stale (report-only).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import rollup  # noqa: E402


def _ws_with_terminal_claim(tmp_path: Path, cid="C-900",
                            terminal="PROVEN") -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "claim-register.yaml").write_text(yaml.safe_dump({"claims": [
        {"id": cid, "status": terminal, "statement": "x"}]}), encoding="utf-8")
    (ws / "runs").mkdir()
    return ws


# ---------- #628: rollup Step 2.5 — notes-due queue ----------

def test_rollup_queues_note_when_missing(tmp_path):
    ws = _ws_with_terminal_claim(tmp_path)
    res = rollup.run_rollup(ws, "C-900", "PROVEN")
    assert res["fired"] is True, res
    due = ws / "runs" / "notes-due.yaml"
    assert due.exists(), "terminal claim without a note must be queued"
    data = yaml.safe_load(due.read_text(encoding="utf-8"))
    assert any(e["claim_id"] == "C-900" for e in data["due"])


def test_rollup_skips_queue_when_note_exists(tmp_path):
    ws = _ws_with_terminal_claim(tmp_path)
    notes = ws / "notes"
    notes.mkdir()
    (notes / "C-900.md").write_text("# durable result note\n", encoding="utf-8")
    res = rollup.run_rollup(ws, "C-900", "PROVEN")
    assert res["fired"] is True
    due = ws / "runs" / "notes-due.yaml"
    if due.exists():
        data = yaml.safe_load(due.read_text(encoding="utf-8")) or {"due": []}
        assert not any(e["claim_id"] == "C-900" for e in data.get("due", []))


def test_rollup_idempotent_queue(tmp_path):
    ws = _ws_with_terminal_claim(tmp_path)
    rollup.run_rollup(ws, "C-900", "PROVEN")
    res2 = rollup.run_rollup(ws, "C-900", "PROVEN")
    assert res2["fired"] is False and res2["reason"] == "already-rolled-up"
    due = ws / "runs" / "notes-due.yaml"
    data = yaml.safe_load(due.read_text(encoding="utf-8"))
    assert sum(1 for e in data["due"] if e["claim_id"] == "C-900") == 1, \
        "no duplicate queue entries on re-rollup"


# #770: bind the scripts TWIN by explicit path (#762 convention) — the ini
# orders hooks before scripts, so a bare import of this shared name resolves
# to the hooks side and is NOT what this suite exercises.
import importlib.util

__cg_spec = importlib.util.spec_from_file_location("completion_gate_scripts", Path(__file__).resolve().parents[1] / "scripts" / "completion_gate.py")
_cg = importlib.util.module_from_spec(__cg_spec)
import sys as _sys
_sys.modules["completion_gate_scripts"] = _cg
__cg_spec.loader.exec_module(_cg)


# ---------- #628: 完工门 reader ----------

def test_completion_gate_notes_due_reader(tmp_path):
    cg = _cg  # #770: by-path scripts twin
    ws = _ws_with_terminal_claim(tmp_path)
    (ws / "runs" / "notes-due.yaml").write_text(
        yaml.safe_dump({"due": [{"claim_id": "C-900", "terminal": "PROVEN"}]}),
        encoding="utf-8")
    assert cg.notes_due(ws) == ["C-900"], "reader surfaces the obligation"


def test_completion_gate_passes_when_no_queue(tmp_path):
    cg = _cg  # #770: by-path scripts twin
    ws = _ws_with_terminal_claim(tmp_path)
    assert cg.notes_due(ws) == [], "absent queue = fail-open (legacy ws)"


def test_completion_gate_passes_when_note_written(tmp_path):
    cg = _cg  # #770: by-path scripts twin
    ws = _ws_with_terminal_claim(tmp_path)
    (ws / "runs" / "notes-due.yaml").write_text(
        yaml.safe_dump({"due": [{"claim_id": "C-900"}]}), encoding="utf-8")
    notes = ws / "notes"; notes.mkdir()
    (notes / "C-900.md").write_text("note\n", encoding="utf-8")
    assert cg.notes_due(ws) == [], "written note clears the obligation"


# ---------- #629: feedback step 10 in the tick ----------

def test_tick_runs_feedback_check_stale(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location(
        "heartbeat_tick_629", ROOT / "scripts" / "heartbeat_tick.py")
    ht = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ht)
    calls = {}

    def fake_run(script, ws_arg, *extra):
        calls[script] = calls.get(script, 0) + 1
        return {"script": script, "rc": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(ht, "run", fake_run)
    monkeypatch.setattr(ht, "_oracle_registered", lambda w: True)
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    rc = ht.main([str(ws)])
    assert rc == 0
    assert calls.get("feedback.py", 0) >= 1, "tick must run feedback.check_stale"
    report = json.loads((ws / "runs" / ".heartbeat-tick.json").read_text(encoding="utf-8"))
    assert "feedback" in report
