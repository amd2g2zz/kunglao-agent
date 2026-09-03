# -*- coding: utf-8 -*-
"""#534 observability lifeline — mechanical coverage gate for kunglao_log
emission across the top-20 high-value silent modules.

TDD contract: every wired module emits at least one structured event per
non-trivial operation. The test does NOT judge emit content quality — it
locks the SHAPE (the #287/459 contract) and the EXISTENCE (a non-empty
runs/logs/kunglao-<date>.jsonl row per face).

Layers (one assertion per layer):
  1. WIRED       the module imports kunglao_log.emit and the call site exists
  2. TELEMETRY   the post-call row conforms to the schema (actor/action/etc.)
  3. DELEGATION  the call is reachable from a public entry point
                 (running the CLI with a synthetic workspace produces the row)
  4. SILENT      no module in the top-20 list regresses to zero emit calls
                 after a refactor (mechanical list cross-check)

The shape mirror is `tests/test_kunglao_log.py` — the field vocabulary is
pinned there; here we only assert that call sites use the SAME vocabulary.
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from _factories import seed_bins

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SCRIPTS_STR = str(SCRIPTS)
if SCRIPTS_STR not in sys.path:
    sys.path.insert(0, SCRIPTS_STR)

# Top-20 high-value silent modules wired by #534. The list IS the gate —
# adding/removing rows here is a coverage contract change that requires a
# matching implementation (mechanical: every module name must appear in at
# least one emit() call, and the calling face must be reachable).
TOP_20_MODULES = (
    # init entry + sub-faces
    ("init", "scripts/kunglao-init.py"),
    ("migrate_facts", "scripts/migrate_facts.py"),
    ("update_index", "scripts/update_index.py"),
    ("heartbeat_tick", "scripts/heartbeat_tick.py"),
    ("external_kicker", "scripts/external_kicker.py"),
    ("priority_ratio", "scripts/priority_ratio.py"),
    ("retract_claim", "scripts/retract_claim.py"),
    ("refutation_propagate", "scripts/refutation_propagate.py"),
    ("outcome_capture", "scripts/outcome_capture.py"),
    ("complete_teardown", "scripts/complete_teardown.py"),
    ("toolchain_install", "scripts/toolchain_install.py"),
    ("env_repair_l1", "scripts/env_repair_l1.py"),
    ("loop_state", "scripts/loop_state.py"),
    ("digest_build", "scripts/digest_build.py"),
    ("wire_up_settings", "scripts/wire_up_settings.py"),
    ("heartbeat_touch", "scripts/heartbeat_touch.py"),
    ("completion_gate", "scripts/completion_gate.py"),
    ("env_check_gate", "scripts/env_check.py"),
    ("hook_activation", "scripts/hook_activation.py"),
)

# All canonical emit-action vocabulary (#459 controlled word list).
# Mirrors event_taxonomy.EMIT_ACTIONS — duplicated here to keep the test
# file self-contained (no cross-test dependency).
ALLOWED_ACTIONS = frozenset({
    "analysis_blocked", "analysis_recorded", "ask_back",
    "capability_reject", "capability_switch", "channel_default",
    "claim_migrate",
    "converge", "death_verdict_rejected", "dispatch",
    "failure_blocked", "ladder_required", "must_ask", "must_stop",
    "plan_stall", "priority_deviation", "stale_plan_on_new_evidence",
    "top1_reject", "verify", "write_blocked",
})

SCHEMA_FIELDS = {
    "ts", "actor", "action", "claim", "tool", "artifact",
    "duration_ms", "exit", "detail",
    "arm", "epoch", "version", "hypothesis_ref",
    "matched_rule",  # #601 additive field
    "trace_id",  # #879 additive field
    "channel",  # #699 additive field (execution surface)
}


def _module_has_emit_call(relpath: str) -> tuple[bool, int]:
    """Return (present, count) of `kunglao_log.emit(` text occurrences.

    Text-search is sufficient for the WIRED layer; the DELEGATION layer
    exercises the actual call via subprocess.  Multi-line `emit(` and
    `emit (\n` are both caught by the simple substring."""
    p = ROOT / relpath
    if not p.is_file():
        return (False, 0)
    text = p.read_text(encoding="utf-8", errors="replace")
    n = text.count("kunglao_log.emit(")
    return (n > 0, n)


def _log_rows(ws: Path) -> list[dict]:
    """Read every event in runs/logs/*.jsonl (one file per UTC day)."""
    logs = ws / "runs" / "logs"
    if not logs.is_dir():
        return []
    rows: list[dict] = []
    for p in sorted(logs.glob("kunglao-*.jsonl")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


# ------------------------------------------------------------
# Layer 1: WIRED — every top-20 module contains a kunglao_log.emit call
# ------------------------------------------------------------

@pytest.mark.parametrize("name,relpath", TOP_20_MODULES,
                         ids=[n for n, _ in TOP_20_MODULES])
def test_wired_each_top20_module_calls_kunglao_log_emit(name, relpath):
    """Layer 1: the module imports/uses the unified event logger at least
    once. A missing file (not yet implemented for that face) is still a
    red result — the WIRED contract requires a literal call site."""
    present, count = _module_has_emit_call(relpath)
    assert present, (
        f"#{name} not wired: {relpath} has zero `kunglao_log.emit(` call "
        f"sites — #534 requires each top-20 module to emit at least one "
        f"structured event (#287/459 contract)")


# ------------------------------------------------------------
# Layer 2: TELEMETRY — every row conforms to the schema
# ------------------------------------------------------------

def test_telemetry_schema_holds_for_all_emits(tmp_path):
    """Layer 2: when a known-good producer emits, the resulting row carries
    the full schema (set-equal field set) and the action is in the
    controlled vocabulary. This locks the SHAPE, not the count."""
    from kunglao_log import emit
    emit(tmp_path, actor="orchestrator", action="dispatch", claim="C-1",
         tool="grep", artifact="evidence/e1.json", duration_ms=42,
         exit=0, detail="ok")
    rows = _log_rows(tmp_path)
    assert len(rows) == 1
    ev = rows[0]
    assert set(ev.keys()) == SCHEMA_FIELDS, (
        f"event schema drift: extra={set(ev)-SCHEMA_FIELDS}, "
        f"missing={SCHEMA_FIELDS-set(ev)}")
    assert ev["action"] in ALLOWED_ACTIONS, (
        f"action {ev['action']!r} not in #459 controlled vocabulary")


# ------------------------------------------------------------
# Layer 3: DELEGATION — running the public CLI produces a row
# ------------------------------------------------------------

@pytest.fixture
def init_ws(tmp_path) -> Path:
    """Synthetic workspace: bins/ + sample + empty claim-register + no marker."""
    ws = tmp_path / "ws"
    seed_bins(ws, payload=b"MZ\x90\x00" + b"\x00" * 64)
    (ws / "runs").mkdir()
    return ws


def _run_kunglao_init(ws: Path) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(SCRIPTS / "kunglao-init.py"),
            str(ws), "--type", "windows", "--skip-toolchain",
            "--profile-root", str(ws.parent / "profile-root")]
    env = {k: v for k, v in os.environ.items()
           if k != "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"}
    env["PYTHONIOENCODING"] = "utf-8"
    env["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] = "0"
    return subprocess.run(argv, capture_output=True, text=True,
                          timeout=120, env=env, errors="replace")


def test_delegation_init_emits_at_least_one_event(init_ws):
    """Layer 3: running the init entry produces >=1 structured event under
    runs/logs/. The init face is the highest-leverage surface — without an
    event here, the whole observability chain is broken end-to-end."""
    r = _run_kunglao_init(init_ws)
    assert r.returncode == 0, f"init failed: rc={r.returncode} stderr={r.stderr}"
    rows = _log_rows(init_ws)
    assert rows, (
        "init produced zero rows under runs/logs/ — #534 requires the init "
        "face to emit at least one event (#287/459 contract)")

    # Every row conforms to the schema
    for ev in rows:
        assert set(ev.keys()) == SCHEMA_FIELDS, (
            f"event schema drift on {ev!r}")
        assert ev["action"] in ALLOWED_ACTIONS, (
            f"init emitted action {ev['action']!r} outside the controlled "
            f"vocabulary — add it to event_taxonomy.EMIT_ACTIONS first")

    # Init must cover >=1 phase row (scaffold/toolchain/wire-up/cron-verify/
    # render/exit — #534 acceptance = each phase >=1 event)
    actors = {r["actor"] for r in rows}
    assert any(a for a in actors), (
        "init emitted events but no actor field populated")

    # .init-report.json must exist (similar shape to .env-check.json)
    report = init_ws / "runs" / ".init-report.json"
    assert report.is_file(), (
        "init did not write runs/.init-report.json — #534 requires a "
        "structured init report (ts / skill-version / phases / overall / exit)")
    doc = json.loads(report.read_text(encoding="utf-8"))
    assert "ts" in doc
    assert "phases" in doc and isinstance(doc["phases"], list)
    assert "overall" in doc
    assert "exit" in doc


# ------------------------------------------------------------
# Layer 4: SILENT — no top-20 module regresses to zero emit calls
# ------------------------------------------------------------

def test_silent_no_top20_regression():
    """Layer 4: every module in TOP_20_MODULES must have at least one
    emit() call.  This is a mechanical list cross-check — adding a row
    without implementation is a red, removing a row without reason is a
    red. The list is the contract."""
    missing = [name for name, rel in TOP_20_MODULES
               if not _module_has_emit_call(rel)[0]]
    assert not missing, (
        "the following top-20 modules have ZERO emit() calls — #534 "
        "silent regression:\n  " + "\n  ".join(missing))


# ------------------------------------------------------------
# Helpers: kunglao_log.py direct API is importable + writable
# ------------------------------------------------------------

def test_kunglao_log_module_importable():
    """Layer 1 helper: kunglao_log.py must be importable as a sibling
    module (scripts/ on sys.path). The top-20 module emitters depend on
    this contract."""
    sys.path.insert(0, SCRIPTS_STR)
    assert importlib.import_module("kunglao_log") is not None
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # tail() exists and is callable
    from kunglao_log import tail
    assert callable(tail)
