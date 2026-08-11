"""TDD RED — tests for scripts/lib_kunglao.py drift detection + external_kicker.should_kick (#43).

Drift = alive-but-stuck: heartbeat fresh + ledger writing + zero state
progress. Time-based dead-session detection (external_kicker.session_is_dead)
cannot see it (F2/F3 regime shift, wf_5c50b792-f7c); ledger SIGNATURE
ROTATION can.

All I/O is SYNTHETIC: pytest tmp_path only. The real
.convergence_ledger.jsonl (D:/works/samples/2026-07-01/malware-analysis-
workspace/) is never read or written — it is only the FORMAT reference
(ts, decision, open_count, open_ids, partial_count, active_workers,
blockers, facts_total).
"""
import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType

import pytest

_HERE = Path(__file__).parent
SCRIPTS = _HERE.parent / "scripts"

# Bare-name `import lib_kunglao` is AMBIGUOUS under pytest: pytest.ini
# pythonpath = ". hooks scripts tools" (hooks first — hooks/worker_budget's
# lazy `from lib_kunglao import scan_active_workers` must resolve to
# hooks/lib_kunglao.py). Production is unambiguous (each script runs with its
# own directory at sys.path[0]). Load scripts/lib_kunglao.py by explicit path
# under a unique name; external_kicker.should_kick uses the SAME loader so
# both share one module instance.
_LIB_NAME = "lib_kunglao_scripts"


def load_scripts_lib() -> ModuleType:
    lib = sys.modules.get(_LIB_NAME)
    if lib is None:
        spec = importlib.util.spec_from_file_location(_LIB_NAME, SCRIPTS / "lib_kunglao.py")
        lib = importlib.util.module_from_spec(spec)
        sys.modules[_LIB_NAME] = lib
        spec.loader.exec_module(lib)
    return lib


_lib = load_scripts_lib()
DRIFT_ESCALATE_ROWS = _lib.DRIFT_ESCALATE_ROWS
ROTATION_WINDOW = _lib.ROTATION_WINDOW
WORKER_PROGRESS_MINUTES = _lib.WORKER_PROGRESS_MINUTES
drift_detected = _lib.drift_detected
signature_rotation = _lib.signature_rotation
workers_progressing = _lib.workers_progressing

sys.path.insert(0, str(SCRIPTS))
from external_kicker import should_kick  # noqa: E402

NOW = datetime.now(timezone.utc)


def ts(minutes_ago: int = 0) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def row(decision: str = "DISPATCH_VERIFIER", **overrides) -> dict:
    """One synthetic ledger row; ts differs per call by default (rotation must
    ignore ts, so identical rows stay identical signatures regardless)."""
    base = {
        "ts": ts(),
        "decision": decision,
        "open_count": 2,
        "open_ids": ["C-001"],
        "partial_count": 1,
        "active_workers": 1,
        "blockers": [],
        "facts_total": 75,
    }
    base.update(overrides)
    return base


def write_ledger(ws: Path, rows: list[dict]) -> Path:
    p = ws / ".convergence_ledger.jsonl"
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                 encoding="utf-8")
    return p


def write_worker_status(ws: Path, minutes_ago: int, name: str = "w1",
                        status: str = "in-progress") -> Path:
    """Synthetic in-progress status file with a controlled mtime."""
    runs = ws / "runs"
    runs.mkdir(exist_ok=True)
    p = runs / f"worker-status-{name}.md"
    p.write_text(f"[{ts()}] step: x | status: {status}\n", encoding="utf-8")
    t = (NOW - timedelta(minutes=minutes_ago)).timestamp()
    os.utime(p, (t, t))
    return p


@pytest.fixture
def ws(tmp_path) -> Path:
    w = tmp_path / "ws"
    w.mkdir()
    return w


# ---------- (a) frozen signature >= window + no worker -> drift ----------

def test_drift_detected_frozen_3_rows_no_worker(ws):
    write_ledger(ws, [row() for _ in range(3)])
    assert signature_rotation(ws) == 3
    assert workers_progressing(ws, now=NOW) is False
    assert drift_detected(ws) is True


# ---------- (b) frozen 3 rows + fresh worker -> legal SATURATED wait ----------

def test_drift_detected_exempts_fresh_worker(ws):
    write_ledger(ws, [row() for _ in range(3)])
    write_worker_status(ws, minutes_ago=5)
    assert workers_progressing(ws, now=NOW) is True
    assert drift_detected(ws) is False


# ---------- (c) rotation 2 < window -> not drift ----------

def test_drift_detected_below_window(ws):
    write_ledger(ws, [row() for _ in range(2)])
    assert signature_rotation(ws) == 2
    assert drift_detected(ws) is False


# ---------- (d) rotation 3 but rows 4-6 changed -> not persistent ----------

def test_should_kick_not_persistent_below_escalate(ws):
    write_ledger(ws, [row(decision="CONVERGED") for _ in range(3)] + [row() for _ in range(3)])
    assert signature_rotation(ws) == 3
    assert should_kick(ws) is False


# ---------- escalation ----------

def test_should_kick_escalates_at_6_frozen_rows(ws):
    write_ledger(ws, [row() for _ in range(6)])
    assert signature_rotation(ws) >= DRIFT_ESCALATE_ROWS
    assert should_kick(ws) is True


def test_should_kick_below_escalation_threshold(ws):
    write_ledger(ws, [row() for _ in range(5)])
    assert signature_rotation(ws) == 5
    assert should_kick(ws) is False


def test_should_kick_fresh_worker_blocks_escalation(ws):
    write_ledger(ws, [row() for _ in range(6)])
    write_worker_status(ws, minutes_ago=5)
    assert should_kick(ws) is False


def test_should_kick_done_worker_does_not_block(ws):
    write_ledger(ws, [row() for _ in range(6)])
    write_worker_status(ws, minutes_ago=5, status="done")
    assert workers_progressing(ws, now=NOW) is False
    assert should_kick(ws) is True


# ---------- signature content (ts / open_count excluded) ----------

def test_rotation_ignores_ts_only_differences(ws):
    rows = [row(ts=ts(i)) for i in range(3)]
    write_ledger(ws, rows)
    assert signature_rotation(ws) == 3


def test_rotation_ignores_open_count_differences(ws):
    rows = [row(ts=ts(i), open_count=i) for i in range(3)]
    write_ledger(ws, rows)
    assert signature_rotation(ws) == 3


def test_rotation_breaks_on_first_differing_field(ws):
    rows = [row() for _ in range(2)] + [row(facts_total=80)] + [row() for _ in range(2)]
    write_ledger(ws, rows)
    assert signature_rotation(ws) == 2


# ---------- corrupt-row robustness ----------

def test_rotation_skips_corrupt_line_without_raising(ws):
    rows = [row() for _ in range(3)]
    rows.insert(1, {"not": "json"})
    write_ledger(ws, rows)
    assert signature_rotation(ws) == 3


def test_rotation_missing_or_empty_ledger_is_zero(ws):
    assert signature_rotation(ws) == 0
    (ws / ".convergence_ledger.jsonl").write_text("", encoding="utf-8")
    assert signature_rotation(ws) == 0


def test_rotation_corrupt_tail_row_uses_last_valid_reference(ws):
    rows = [row() for _ in range(3)] + ["garbage{{{"]
    write_ledger(ws, rows)
    assert signature_rotation(ws) == 3


# ---------- workers_progressing edges ----------

def test_workers_progressing_stale_in_progress_file(ws):
    write_worker_status(ws, minutes_ago=45)
    assert workers_progressing(ws, now=NOW) is False


def test_workers_progressing_no_files(ws):
    assert workers_progressing(ws, now=NOW) is False


def test_workers_progressing_done_file(ws):
    write_worker_status(ws, minutes_ago=5, status="done")
    assert workers_progressing(ws, now=NOW) is False


def test_workers_progressing_scans_worktree_runs(ws):
    wt_runs = ws.parent / ".wt-01" / "malware-analysis-workspace" / "runs"
    wt_runs.mkdir(parents=True)
    p = wt_runs / "worker-status-wt1.md"
    p.write_text(f"[{ts()}] step: x | status: in-progress\n", encoding="utf-8")
    t = (NOW - timedelta(minutes=5)).timestamp()
    os.utime(p, (t, t))
    assert workers_progressing(ws, now=NOW) is True


# ---------- constants wiring ----------

def test_constants_wired():
    assert ROTATION_WINDOW == 3
    assert DRIFT_ESCALATE_ROWS == 6
    assert WORKER_PROGRESS_MINUTES == 20
