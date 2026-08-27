# -*- coding: utf-8 -*-
"""tests/test_ledger_stdlib_584.py — #584: the hand-rolled JSONL ledger moves
onto stdlib handlers (format byte-identical).

Adjudicated sequencing: AFTER #629 (merged — the rollup wiring landed first).
Facts from the survey: the "Python 3.13 JSONHandler" the issue cited does NOT
exist in the stdlib; the real option is json + logging.handlers.WatchedFileHandler
(rotation-safe reopen, stdlib-native). The .convergence_ledger.jsonl line
format is a CONTRACT (external_kicker._ledger_last_snapshot reads it) —
byte-identical round-trip is the gate.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import rollup  # noqa: E402


def _entry(claim="C-700", ts="2026-08-25T00:00:00Z") -> dict:
    return {"type": "operator_action", "action": "rollup",
            "claim_id": claim, "terminal_status": "PROVEN", "ts": ts}


def test_append_uses_stdlib_handler(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir()
    rollup._append_ledger(ws, _entry())
    src = (ROOT / "scripts" / "rollup.py").read_text(encoding="utf-8")
    assert "WatchedFileHandler" in src, "stdlib handler per adjudication (#584)"


def test_line_format_byte_identical(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir()
    e = _entry()
    rollup._append_ledger(ws, e)
    line = (ws / ".convergence_ledger.jsonl").read_text(encoding="utf-8")
    assert line == json.dumps(e, ensure_ascii=False) + "\n", \
        "the ledger line format is a contract (external_kicker reads it)"


def test_rolled_up_read_still_works(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir()
    rollup._append_ledger(ws, _entry(claim="C-701"))
    assert rollup._rolled_up(ws, "C-701", "PROVEN") is True
    assert rollup._rolled_up(ws, "C-702", "PROVEN") is False
