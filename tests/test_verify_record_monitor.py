# -*- coding: utf-8 -*-
"""Phase 5 contract tests: M3 VERIFY / M4 RECORD / M5 MONITOR.

Step 1 RED — current state: kunglao-verify.py / kunglao-record.py /
kunglao-monitor.py absent → the import itself is RED.

GREEN targets (phase 5 criteria, E5.1-E5.3):
- E5.1 Expand: verify/record asides; the old CLIs keep diffing empty
- E5.2 Migrate: reconciler N=3 rounds, zero checksum drift
- E5.3 Contract: the old channel is read-only

Core behaviors:
- L1 mechanical layer: parse_reproduce → run (read-only whitelist) → sha256
  compare against expected → PASS/FAIL
- L2 adversarial layer: dispatch kunglao-redteam (independent subagent,
  BLIND); output CONFIRMED|REFUTED|UNVERIFIED-WITH-GAP
- anchor_check: a PASS must carry anchors — no anchor, no promotion
- ledger idempotency: recording the same event_id twice → 1 entry
- claims migration: a non-orchestrator writing a terminal state → rejected
  (maker-checker)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


# ---------- L1 mechanical-layer discrimination ----------

def _write_fact(ws: Path, fid: str, claim: str, reproduce: str, expected: str) -> Path:
    f = ws / "facts" / f"{fid}.md"
    f.write_text(
        f"---\nid: {fid}\nclaim: {claim}\nreproduce: {reproduce}\nexpected: {expected}\n---\n",
        encoding="utf-8")
    return f


def test_known_fact_pass_fake_fact_fail(ws_factory, contract_validator) -> None:
    """E5 discrimination: a known PROVEN fact → PASS; a fake fact with tampered expected → FAIL."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    facts = ws / "facts"
    facts.mkdir()

    # real fact: reproduce output matches expected
    _write_fact(ws, "F-001", "Decode PE magic", "import struct; print(hex(0x5A4D))", "0x5a4d")
    # fake fact: expected tampered (does not match the reproduce output)
    _write_fact(ws, "F-002", "Decode PE magic", "import struct; print(hex(0x5A4D))", "0xdeadbeef")

    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "kunglao-verify.py"), str(ws), "F-001", "--json"],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"kunglao-verify F-001 failed: {r.stderr}"
    out = json.loads(r.stdout)
    contract_validator("verify-output", out)
    assert out["l1"]["verdict"] == "PASS", f"known fact should PASS: {out}"

    r2 = subprocess.run(
        [sys.executable, str(SCRIPTS / "kunglao-verify.py"), str(ws), "F-002", "--json"],
        capture_output=True, text=True, timeout=60)
    out2 = json.loads(r2.stdout)
    assert out2["l1"]["verdict"] == "FAIL", f"fake fact should FAIL: {out2}"


def test_anchor_check_blocks_no_anchor(ws_factory) -> None:
    """An anchor-less PASS refuses promotion: anchor_check(verdict) with no anchors → False."""
    from kunglao_verify import anchor_check
    v = {"l1": {"verdict": "PASS"}, "anchors": []}
    assert anchor_check(v) is False, "no-anchor PASS must be blocked"


# ---------- M4 ledger idempotency ----------

def test_ledger_idempotent_same_event_once(ws_factory) -> None:
    """Recording the same event_id twice → 1 entry."""
    ws = ws_factory()
    from kunglao_record import record_event, read_events
    ev = {"source_module": "test", "event_type": "fact_written",
          "payload": {"fact_id": "F-001", "claim_id": "C-1"}}
    seq1 = record_event(ws, ev)
    seq2 = record_event(ws, ev)
    assert seq1 == seq2, f"idempotent record should return same seq: {seq1} vs {seq2}"
    events = read_events(ws, "fact_written")
    assert len(events) == 1, f"duplicate event recorded: {len(events)}"


# ---------- M5 monitor TickOutput schema ----------

def test_monitor_tick_output_schema(ws_factory, contract_validator) -> None:
    """TickOutput validation: heartbeat/active_workers/health/next fields."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "kunglao-monitor.py"), str(ws), "--json"],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"kunglao-monitor failed: {r.stderr}"
    out = json.loads(r.stdout)
    contract_validator("tick-output", out)


# ---------- M4 claim migration maker-checker ----------

def test_claim_migrator_blocks_worker_terminal(ws_factory) -> None:
    """A non-orchestrator writing a terminal state → rejected."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    from kunglao_record import claim_migrator
    ok, reason = claim_migrator(ws, "C-1", "PROVEN", actor="worker-w1")
    assert not ok, f"worker terminal write must be rejected: {reason}"
