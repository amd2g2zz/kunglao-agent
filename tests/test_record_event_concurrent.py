# -*- coding: utf-8 -*-
"""tests/test_record_event_concurrent.py -- Issue #96 F8: record_event
Whole-ledger rewrite race under concurrency causes event loss.

RED phase: two events record_event different event_ids onto the same ledger concurrently,
verify both survive (currently fail; whole-ledger rewrite loses the later writer).
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def test_concurrent_record_events_no_loss(tmp_path):
    """Two different events written concurrently must both survive in ledger.

    Current bug: record_event reads entire ledger, checks idempotency, then
    does full atomic rewrite (read-modify-write). If two threads write
    concurrently, the second writer's read sees the pre-first-writer state
    and overwrites the first writer's append -- event lost.

    Fix: use open(path, 'a') append mode (OS guarantees atomicity for
    writes <= PIPE_BUF on POSIX / Windows) so both writes survive.
    """
    ws = tmp_path / "ws-concurrent"
    ws.mkdir()
    sys_path = str(SCRIPTS)
    barrier = threading.Barrier(2)

    errors: list[str] = []

    def _record(event: dict):
        """Run record_event in a subprocess to isolate module-level state,
        but use direct function call with barrier for tighter concurrency."""
        try:
            from kunglao_record import record_event
            # Both threads hit the barrier simultaneously so they interleave
            barrier.wait(timeout=5)
            seq = record_event(ws, event)
            if seq <= 0:
                errors.append(f"non-positive seq {seq} for {event}")
        except Exception as exc:
            errors.append(f"exception: {exc}")

    ev_a = {"source_module": "worker-a", "event_type": "fact_written",
            "payload": {"fact_id": "F-100", "claim_id": "C-100"}}
    ev_b = {"source_module": "worker-b", "event_type": "fact_verified",
            "payload": {"fact_id": "F-200", "claim_id": "C-200"}}

    t1 = threading.Thread(target=_record, args=(ev_a,))
    t2 = threading.Thread(target=_record, args=(ev_b,))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert not errors, f"recording errors: {errors}"

    # Read ledger back and verify both events are present
    from kunglao_record import read_events
    all_events = read_events(ws)
    event_ids = {e.get("event_id") for e in all_events}

    eid_a = ev_a["event_type"] + json.dumps(ev_a["payload"], sort_keys=True,
                                              separators=(",", ":"))
    eid_b = ev_b["event_type"] + json.dumps(ev_b["payload"], sort_keys=True,
                                              separators=(",", ":"))
    from kunglao_record import event_id_of
    expected_a = event_id_of(ev_a["event_type"], ev_a["payload"])
    expected_b = event_id_of(ev_b["event_type"], ev_b["payload"])

    assert expected_a in event_ids, (
        f"event A lost! event_ids={event_ids}, expected_a={expected_a}")
    assert expected_b in event_ids, (
        f"event B lost! event_ids={event_ids}, expected_b={expected_b}")
    assert len(all_events) == 2, (
        f"expected 2 events, got {len(all_events)}: {all_events}")


def test_concurrent_many_events_no_loss(tmp_path):
    """Stress test: 10 threads each writing a unique event concurrently.
    All 10 must survive in the ledger."""
    ws = tmp_path / "ws-many"
    ws.mkdir()
    n = 10
    barrier = threading.Barrier(n)
    errors: list[str] = []

    def _record(idx: int):
        try:
            from kunglao_record import record_event
            barrier.wait(timeout=5)
            record_event(ws, {
                "source_module": f"worker-{idx}",
                "event_type": "fact_written",
                "payload": {"fact_id": f"F-{idx:03d}", "claim_id": f"C-{idx:03d}"}
            })
        except Exception as exc:
            errors.append(f"thread-{idx}: {exc}")

    threads = [threading.Thread(target=_record, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert not errors, f"errors: {errors}"

    from kunglao_record import read_events, event_id_of
    all_events = read_events(ws)
    expected_ids = {
        event_id_of("fact_written",
                     {"fact_id": f"F-{i:03d}", "claim_id": f"C-{i:03d}"})
        for i in range(n)
    }
    actual_ids = {e.get("event_id") for e in all_events}

    missing = expected_ids - actual_ids
    assert not missing, f"lost events: {missing}"
    assert len(all_events) == n, (
        f"expected {n} events, got {len(all_events)}")


def test_idempotency_preserved_under_append_mode(tmp_path):
    """Idempotency must still work: same event_id recorded twice = 1 entry."""
    ws = tmp_path / "ws-idempotent"
    ws.mkdir()
    from kunglao_record import record_event, read_events
    ev = {"source_module": "test", "event_type": "fact_written",
          "payload": {"fact_id": "F-001", "claim_id": "C-001"}}
    seq1 = record_event(ws, ev)
    seq2 = record_event(ws, ev)
    assert seq1 == seq2, f"idempotent: {seq1} != {seq2}"
    events = read_events(ws, "fact_written")
    assert len(events) == 1, f"expected 1 event, got {len(events)}"


def test_seq_increments_monotonically(tmp_path):
    """seq values must increment with each new event."""
    ws = tmp_path / "ws-seq"
    ws.mkdir()
    from kunglao_record import record_event, read_events
    for i in range(5):
        record_event(ws, {
            "source_module": "test",
            "event_type": "fact_written",
            "payload": {"fact_id": f"F-{i:03d}", "claim_id": f"C-{i:03d}"}
        })
    events = read_events(ws)
    seqs = [e["seq"] for e in events]
    assert seqs == [1, 2, 3, 4, 5], f"seqs not monotonic: {seqs}"


def test_read_events_still_works(tmp_path):
    """read_events must still parse ledger correctly after append-mode writes."""
    ws = tmp_path / "ws-read"
    ws.mkdir()
    from kunglao_record import record_event, read_events, event_id_of
    ev = {"source_module": "test", "event_type": "claim_promoted",
          "payload": {"claim_id": "C-1", "status": "PROVEN"}}
    record_event(ws, ev)
    events = read_events(ws, "claim_promoted")
    assert len(events) == 1
    assert events[0]["event_id"] == event_id_of("claim_promoted", ev["payload"])
    assert events[0]["seq"] == 1
    assert "checksum" in events[0]
