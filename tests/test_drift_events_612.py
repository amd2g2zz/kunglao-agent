# -*- coding: utf-8 -*-
"""tests/test_drift_events_612.py — #612: drift detection must be a mechanism,
not manual smart-pings.

RED (adjudicated facts, production 3 incidents ~4h): NO existing countermeasure
detected either drift flavor — planning workers were invisible (#607 fixed the
visibility half); in-progress-but-stalled workers entered the stuck list but
nothing checked whether evidence was being produced. Adjudicated fix (方案 A):
stuck + empty evidence for the worker's claim → a drift event, recorded to
runs/.drift-events.jsonl (append-only). Advisory-only (#88): never blocks.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

# module name is kunglao-monitor.py (hyphen) → importlib by path
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("kunglao_monitor", ROOT / "scripts" / "kunglao-monitor.py")
km = _ilu.module_from_spec(_spec); sys.modules["kunglao_monitor"] = km; _spec.loader.exec_module(km)  # noqa: E402


def _backdate(p: Path, minutes: int) -> None:
    old = time.time() - minutes * 60
    os.utime(p, (old, old))


def _mk_worker(ws: Path, stem: str, status: str, age_min: int,
               backtrack: str | None = None) -> Path:
    runs = ws / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    p = runs / f"worker-status-{stem}.md"
    body = f"[10:00] step: started | status: {status}\n"
    if backtrack:
        body += f"## backtrack\ndecision: {backtrack}\n"
    p.write_text(body, encoding="utf-8")
    _backdate(p, age_min)
    return p


def _stale_in_progress(ws: Path, stem: str, age_min: int,
                       backtrack: str | None = "continue") -> Path:
    """Aged in-progress WITH a valid backtrack (so stuck_watch's backtrack
    filter passes) — the Flavor-B shape that used to pass silently."""
    return _mk_worker(ws, stem, "in-progress", age_min, backtrack)


# ---------- drift_events: stuck + empty evidence ----------

def test_stuck_with_empty_evidence_emits_drift(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir()
    _stale_in_progress(ws, "C201", age_min=km.STUCK_MIN + 10)
    events = km.detect_drift(ws)
    assert len(events) == 1
    assert events[0]["worker"] == "worker-status-C201.md"
    assert events[0]["flavor"] == "stuck-no-evidence"


def test_drift_event_appended_to_jsonl(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir()
    _stale_in_progress(ws, "C202", age_min=km.STUCK_MIN + 5)
    km.detect_drift(ws)
    ledger = ws / "runs" / ".drift-events.jsonl"
    assert ledger.exists()
    rows = [json.loads(ln) for ln in ledger.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert rows and rows[-1]["worker"].endswith("C202.md")
    assert "ts" in rows[-1] and rows[-1]["ts"].endswith("Z")


def test_stuck_with_fresh_evidence_not_drift(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir()
    _stale_in_progress(ws, "C203", age_min=km.STUCK_MIN + 5)
    facts = ws / "facts"; facts.mkdir()
    (facts / "F203.md").write_text("# F203\n", encoding="utf-8")
    assert km.detect_drift(ws) == []


def test_fresh_worker_not_drift(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir()
    _mk_worker(ws, "C204", "in-progress", age_min=1, backtrack="continue")
    assert km.detect_drift(ws) == []


def test_planning_stale_worker_emits_drift(tmp_path):
    """Flavor A (post-#607 visibility): aged planning worker, zero artifacts."""
    ws = tmp_path / "ws"; ws.mkdir()
    _mk_worker(ws, "C205", "planning", age_min=km.STUCK_MIN + 10)
    events = km.detect_drift(ws)
    assert len(events) == 1 and events[0]["flavor"] == "stuck-no-evidence"
