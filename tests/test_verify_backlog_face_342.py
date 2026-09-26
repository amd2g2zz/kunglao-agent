# -*- coding: utf-8 -*-
"""Issue #342 Part C — verify_backlog tick-report face.

ONE report field in the heartbeat tick report (max PARTIAL age in ticks +
backlog count), the same fail-open pattern as the h_bits / rank faces:
computed AFTER the main report serialization and re-written into
runs/.heartbeat-tick.json, any failure lands in the stderr WARN channel and
never fails the tick. No new tick steps, no distillation (owner restraint).

The face shares the #342 age reader (convergence_check.partial_fact_ages)
with the VERIFY_STALE event — one implementation, no drift.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TICK = ROOT / "scripts" / "heartbeat_tick.py"
SCRIPTS = TICK.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

STALE_DAY = (datetime.now(timezone.utc) - timedelta(days=2)).date().isoformat()


def _make_ws(tmp_path: Path, name: str = "ws") -> Path:
    """Minimal tick workspace (the test_heartbeat_tick convention)."""
    ws = tmp_path / name
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    return ws


def _emit_settlement_event(ws: Path) -> None:
    """H1a: the verify-backlog face rides the tick report only when the
    pass consumed a ledger event — one settlement row wakes it."""
    import kunglao_log
    kunglao_log.emit(ws, "test", "claim_settled", detail="h1-face-gate")


def _tick(ws: Path) -> tuple[dict, subprocess.CompletedProcess]:
    _emit_settlement_event(ws)  # H1a: the face under test is event-gated
    r = subprocess.run(
        [sys.executable, str(TICK), str(ws)],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120,
    )
    report = json.loads(
        (ws / "runs" / ".heartbeat-tick.json").read_text(encoding="utf-8"))
    return report, r


def _seed_partial(ws: Path, fact_id: str, created: str) -> None:
    fdir = ws / "facts"
    fdir.mkdir(exist_ok=True)
    (fdir / "_INDEX.md").write_text(
        f"# _INDEX\n{fact_id} | PARTIAL | C-001 | x\n", encoding="utf-8")
    (fdir / f"{fact_id}.md").write_text(
        f"---\nid: {fact_id}\ntype: fact\nstatus: INFERRED\n"
        f"created: {created}\nclaim_id: C-001\n---\n\nbody.\n",
        encoding="utf-8")


def test_tick_report_carries_verify_backlog(tmp_path):
    """max PARTIAL age (ticks) + count ride the report."""
    ws = _make_ws(tmp_path)
    _seed_partial(ws, "F001", STALE_DAY)
    report, _ = _tick(ws)
    vb = report.get("verify_backlog")
    assert isinstance(vb, dict), f"verify_backlog face missing: {report.keys()}"
    assert vb["count"] == 1
    assert isinstance(vb["max_age_ticks"], (int, float))
    # 2 days at the 5-min cadence is ~576 ticks — far past any jitter
    assert vb["max_age_ticks"] > 12


def test_tick_report_backlog_empty_workspace(tmp_path):
    """No partials -> the honest zero face (count 0, age None), never a
    fabricated number."""
    ws = _make_ws(tmp_path)
    report, _ = _tick(ws)
    vb = report.get("verify_backlog")
    assert isinstance(vb, dict)
    assert vb["count"] == 0
    assert vb["max_age_ticks"] is None


def test_tick_survives_corrupt_fact_face(tmp_path):
    """Fail-open: an unreadable facts face must not fail the tick (the
    h_bits/rank pattern — WARN channel, tick exits on its own rc)."""
    ws = _make_ws(tmp_path)
    fdir = ws / "facts"
    fdir.mkdir()
    (fdir / "_INDEX.md").write_text("\xff\xfe not utf8 at all", encoding="utf-8")
    report, proc = _tick(ws)
    vb = report.get("verify_backlog")
    assert isinstance(vb, dict)
    assert vb["count"] == 0
    # the tick's own verdict semantics are untouched
    assert proc.returncode in (0, 1)


def test_face_module_standalone(tmp_path):
    """The face module reads one workspace without the tick (statusline /
    resume consumers) and never raises on a missing workspace."""
    import verify_backlog_face
    face = verify_backlog_face.face(tmp_path / "does-not-exist")
    assert face["verify_backlog"]["count"] == 0
    ws = _make_ws(tmp_path)
    _seed_partial(ws, "F001", STALE_DAY)
    face = verify_backlog_face.face(ws)
    assert face["verify_backlog"]["count"] == 1
    assert face["verify_backlog"]["max_age_ticks"] > 12
