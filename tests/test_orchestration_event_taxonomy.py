# -*- coding: utf-8 -*-
"""tests/test_orchestration_event_taxonomy.py — #309 event classification (merged #287).

Absorbed idea (amruth-sn/kong events.py:19-62), re-implemented for kunglao:
a 25-class EventType taxonomy mapped onto the EXISTING kunglao event sources
and rendered for the Claude-native interface (statusline JSON + per-round
digest). No new state format, no TUI.

Review r1-309 requirement: fixtures mirror REAL producer conventions, not the
implementation's vocabulary —
  - worker files: append-only log lines "[HH:MM] step: ... | status: in-progress"
    / dedicated "status: done|blocked" lines (agents/kunglao-worker.md:54,
    convergence_check, worker_pulse); LAST status line wins
  - blockers: file present without INVALIDATED marker = active
    (convergence_check._active_blockers); INVALIDATED / blockers/.resolved/ =
    resolved (stale_blocker_prune); NO producer writes "state: OPEN/RESOLVED"
  - gate_blocked: failure_analysis_gate.scan_workspace entries with
    state == "BLOCKED" (the source priority.py consumes)
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import event_taxonomy as et

# real worker log shapes (agents/kunglao-worker.md + lib_kunglao both-shapes)
IN_PROGRESS_LOG = "[12:00] step: started floss | status: in-progress"
DONE_LOG = "[12:05] step: done | status: done"
BLOCKED_LOG = "[12:20] step: blocked on tool | status: blocked"


def _write_ledger(ws: Path, rows: list[dict]) -> None:
    (ws / "ledger.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8")


def _write_convergence(ws: Path, rows: list[dict]) -> None:
    (ws / ".convergence_ledger.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8")


def test_catalog_has_exactly_25_types():
    assert len(et.ALL_EVENT_TYPES) == 25
    assert len(set(et.ALL_EVENT_TYPES)) == 25


def test_classify_ledger_event_stream():
    assert et.classify_event({"event_type": "fact_written"}, source="ledger") == "fact_written"
    assert et.classify_event({"event_type": "fact_verified"}, source="ledger") == "fact_verified"
    assert et.classify_event({"event_type": "claim_promoted"}, source="ledger") == "claim_promoted"
    assert et.classify_event({"event_type": "claim_refuted"}, source="ledger") == "claim_refuted"
    assert et.classify_event({"event_type": "failure_recorded"}, source="ledger") == "failure_recorded"
    assert et.classify_event({"event_type": "intent_opened"}, source="ledger") == "intent_opened"
    assert et.classify_event({"event_type": "intent_closed"}, source="ledger") == "intent_closed"
    assert et.classify_event({"event_type": "unknown_kind"}, source="ledger") is None


def test_classify_convergence_ledger_rows():
    assert et.classify_event({"type": "snapshot", "decision": "DISPATCH"},
                             source="convergence") == "snapshot"
    assert et.classify_event({"type": "outcome", "result": "passes"},
                             source="convergence") == "outcome_passed"
    assert et.classify_event({"type": "outcome", "result": "CONFIRMED"},
                             source="convergence") == "outcome_passed"
    assert et.classify_event({"type": "outcome", "result": "partial"},
                             source="convergence") == "outcome_partial"
    assert et.classify_event({"type": "outcome", "result": "fails"},
                             source="convergence") == "outcome_failed"
    assert et.classify_event({"type": "outcome", "result": "REFUTED"},
                             source="convergence") == "outcome_failed"
    assert et.classify_event({"type": "operator_action"},
                             source="convergence") == "operator_action"
    assert et.classify_event({"type": "snapshot"}, source="convergence") == "snapshot"
    assert et.classify_event({"type": "bogus"}, source="convergence") is None


def test_worker_status_map_matches_producer_vocabulary():
    """Lock the map to the vocabulary REAL producers emit
    (agents/kunglao-worker.md:54, convergence_check docstring, worker_pulse).
    Any value outside {in-progress, done, blocked} would be a dead class."""
    assert set(et.WORKER_STATUS_MAP) == {"in-progress", "done", "blocked"}


def test_classify_worker_status_lines():
    assert et.classify_worker_status("in-progress") == "worker_step"
    assert et.classify_worker_status("done") == "worker_completed"
    assert et.classify_worker_status("blocked") == "worker_failed"
    # values no producer emits classify as None (never invented)
    assert et.classify_worker_status("active") is None
    assert et.classify_worker_status("started") is None
    assert et.classify_worker_status("mystery") is None


def test_classify_claim_register_statuses():
    assert et.classify_claim_status("PROVEN") == "claim_promoted"
    assert et.classify_claim_status("VERIFIED") == "claim_promoted"
    assert et.classify_claim_status("REFUTED") == "claim_refuted"
    assert et.classify_claim_status("PARTIALLY-VERIFIED") == "claim_partial"
    assert et.classify_claim_status("DEFERRED") == "claim_deferred"
    assert et.classify_claim_status("SUPERSEDED") == "claim_superseded"
    assert et.classify_claim_status("DEAD") == "claim_dead"
    assert et.classify_claim_status("OPEN") is None  # OPEN is not an event


def test_workspace_scan_counts_real_formats(tmp_path):
    ws = tmp_path
    _write_ledger(ws, [
        {"event_type": "fact_written", "payload": {}},
        {"event_type": "fact_verified", "payload": {}},
        {"event_type": "claim_promoted", "payload": {}},
    ])
    _write_convergence(ws, [
        {"type": "snapshot", "decision": "DISPATCH", "ts": "t1"},
        {"type": "outcome", "claim_id": "C-1", "checker": "verify-note",
         "result": "passes", "ts": "t2"},
        {"type": "operator_action", "ts": "t3", "action": "x"},
    ])
    runs = ws / "runs"
    runs.mkdir()
    (runs / "worker-status-w1.md").write_text(
        f"{IN_PROGRESS_LOG}\n", encoding="utf-8")
    (runs / "worker-status-w2.md").write_text(
        f"{IN_PROGRESS_LOG}\n{DONE_LOG}\n", encoding="utf-8")
    (runs / "verify-redteam-1.md").write_text(
        "RED-TEAM VERDICT: CONFIRMED\n", encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        "claims:\n"
        "- id: C-1\n  status: PROVEN\n  statement: x\n  promotion_attempts: 0\n"
        "- id: C-2\n  status: DEFERRED\n  statement: y\n  promotion_attempts: 0\n",
        encoding="utf-8")

    counts = et.classify_workspace(ws)
    assert counts["fact_written"] == 1
    assert counts["fact_verified"] == 1
    assert counts["claim_promoted"] == 2  # ledger event + register PROVEN
    assert counts["snapshot"] == 1
    assert counts["outcome_passed"] == 1
    assert counts["operator_action"] == 1
    assert counts["worker_started"] == 2  # both worker logs open with in-progress
    assert counts["worker_step"] == 1  # w1 still in-progress
    assert counts["worker_completed"] == 1  # w2 last line done
    assert counts["redteam_verdict"] == 1
    assert counts["claim_deferred"] == 1
    assert counts["gate_blocked"] == 0  # terminal claims need no analysis


def test_worker_stuck_detected_via_stale_heartbeat(tmp_path):
    ws = tmp_path
    runs = ws / "runs"
    runs.mkdir()
    p = runs / "worker-status-w1.md"
    p.write_text(f"{IN_PROGRESS_LOG}\n", encoding="utf-8")
    old = time.time() - 2 * 86400  # 2 days ago (real cutoff: 20 min)
    os.utime(p, (old, old))
    counts = et.classify_workspace(ws)
    assert counts["worker_stuck"] == 1
    assert counts["worker_step"] == 0
    assert counts["worker_started"] == 1


def test_worker_blocked_counts_as_failed(tmp_path):
    ws = tmp_path
    runs = ws / "runs"
    runs.mkdir()
    (runs / "worker-status-w1.md").write_text(
        f"{IN_PROGRESS_LOG}\n{BLOCKED_LOG}\n", encoding="utf-8")
    counts = et.classify_workspace(ws)
    assert counts["worker_failed"] == 1
    assert counts["worker_started"] == 1
    assert counts["worker_step"] == 0


def test_blockers_scanned_real_lifecycle(tmp_path):
    """Real lifecycle: active = no INVALIDATED marker; resolved = INVALIDATED
    marker or moved to blockers/.resolved/ (stale_blocker_prune)."""
    ws = tmp_path
    blk = ws / "blockers"
    blk.mkdir()
    (blk / "b1.md").write_text("blocker for C-1: floss unavailable\n", encoding="utf-8")
    (blk / "b2.md").write_text(
        "blocker for C-2\nINVALIDATED 2026-08-14 (claim PROVEN)\n", encoding="utf-8")
    resolved = blk / ".resolved"
    resolved.mkdir()
    (resolved / "b3.md").write_text("pruned stale blocker\n", encoding="utf-8")
    counts = et.classify_workspace(ws)
    assert counts["blocker_opened"] == 1
    assert counts["blocker_resolved"] == 2
    assert counts["gate_blocked"] == 0


def test_gate_blocked_from_real_failure_analysis(tmp_path):
    """gate_blocked = failure_analysis_gate.scan_workspace BLOCKED entries —
    a claim with a failed attempt (promotion_attempts > 0), non-terminal,
    and no analyses/failure-<claim>.yaml (the source priority.py consumes)."""
    ws = tmp_path
    (ws / "claim-register.yaml").write_text(
        "claims:\n"
        "- id: C-G\n  status: OPEN\n  statement: x\n  promotion_attempts: 1\n",
        encoding="utf-8")
    counts = et.classify_workspace(ws)
    assert counts["gate_blocked"] == 1


def test_gate_blocked_cleared_by_current_analysis(tmp_path):
    """A current failure analysis (covers_attempt >= promotion_attempts AND
    the #495 three artifacts present) clears the BLOCKED state — the gate is
    satisfied."""
    ws = tmp_path
    (ws / "claim-register.yaml").write_text(
        "claims:\n"
        "- id: C-G\n  status: OPEN\n  statement: x\n  promotion_attempts: 1\n",
        encoding="utf-8")
    adir = ws / "analyses"
    adir.mkdir()
    (adir / "failure-C-G.yaml").write_text(
        "method_assumption: floss\nassumption_validity: not-justified\n"
        "next_method: pefile\ncovers_attempt: 1\n"
        "validated_capability: floss ran to completion\n"
        "identified_obstacle: binary is packed\n"
        "next_method_source: lesson-hit\n",
        encoding="utf-8")
    counts = et.classify_workspace(ws)
    assert counts["gate_blocked"] == 0


def test_statusline_json(tmp_path):
    ws = tmp_path
    runs = ws / "runs"
    runs.mkdir()
    (runs / "worker-status-w1.md").write_text(
        f"{IN_PROGRESS_LOG}\n{BLOCKED_LOG}\n", encoding="utf-8")
    payload = et.statusline_json(ws)
    assert payload["schema"].startswith("kunglao-event-statusline")
    assert payload["counts"]["worker_failed"] == 1
    assert payload["counts"]["worker_started"] == 1
    assert isinstance(payload["alerts"], list)
    assert any(a.startswith("worker_failed") for a in payload["alerts"])


def test_round_digest_text_short_and_mechanical(tmp_path):
    ws = tmp_path
    _write_ledger(ws, [{"event_type": "fact_written", "payload": {}}])
    text = et.round_digest_text(ws)
    assert "fact_written" in text
    assert len(text.splitlines()) <= 10


def test_cli_reproduce_prints_field_value(tmp_path, capsys):
    """--reproduce emits field=value lines parseable by kunglao_verify's
    reproduce output parser (one field[:=]value per line)."""
    ws = tmp_path
    rc = et.main([str(ws), "--reproduce"])
    assert rc == 0
    out = capsys.readouterr().out
    assert f"workspace={ws}" in out
    for line in out.strip().splitlines():
        assert re.match(r"^\w+\s*[:=]\s*.+$", line), line
