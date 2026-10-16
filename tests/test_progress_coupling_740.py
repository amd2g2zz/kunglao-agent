# -*- coding: utf-8 -*-
"""tests/test_progress_coupling_740.py — the tick machinery runs on input
change, not on clock (issue 740, Face 1).

RC1 live evidence: ~500 t2_queue_built events vs 36 dispatches in 5
hours — every SubagentStop rebuilt and re-emitted the priority queue
even when nothing changed, because the queue's ``age_min`` projection
moves with the clock and made every build content-new. The treadmill
burned the token budget that the analysis needed.

The fix: the round-close face computes the queue's INPUT signature —
(claim_id, status, stalled, priority) per entry, deliberately EXCLUDING
the time projections (age_min, reason, ts) — and skips both the persist
and the emit when the signature is unchanged. A stall-floor crossing or
a register change IS a real change and rebuilds. The drain face keeps
its semantics byte-identically (consumption is a real change).

All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import verification_ladder as vl  # noqa: E402

T0 = datetime(2026, 10, 17, 8, 0, 0, tzinfo=timezone.utc)


def _ws(tmp_path: Path, claims: list[dict]) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True),
        encoding="utf-8")
    return ws


def _emit_spy(monkeypatch):
    import kunglao_log
    calls: list[tuple[str, str]] = []

    def _spy(ws, actor, action, **kw):
        calls.append((actor, action))

    monkeypatch.setattr(kunglao_log, "emit", _spy)
    return calls


def _queue_file(ws: Path) -> Path:
    return ws / "runs" / "t2-queue.json"


# ---------- 1. unchanged inputs skip the churn ------------------------------

def test_unchanged_inputs_skip_persist_and_emit(tmp_path, monkeypatch):
    """Two round-closes over the same register within the stall window:
    the second persists nothing and emits nothing — the persisted queue
    is still true. The RC1 treadmill was 500 rebuilds of exactly this
    no-change shape."""
    ws = _ws(tmp_path, [{"id": "C-1", "status": "OPEN"}])
    spy = _emit_spy(monkeypatch)
    vl.round_close(ws, now=T0)
    n1 = sum(1 for a, act in spy if act == "t2_queue_built")
    before = _queue_file(ws).read_text(encoding="utf-8")

    vl.round_close(ws, now=T0 + timedelta(minutes=1))   # clock moves, no crossing
    n2 = sum(1 for a, act in spy if act == "t2_queue_built")
    assert n2 == n1                              # no re-emit
    assert _queue_file(ws).read_text(encoding="utf-8") == before


def test_repeated_unchanged_ticks_do_not_accumulate_emits(
        tmp_path, monkeypatch):
    """The RC1 shape directly: ten no-change round-closes emit ONE
    t2_queue_built total (the first), not ten."""
    ws = _ws(tmp_path, [{"id": "C-1", "status": "OPEN"},
                        {"id": "C-2", "status": "BLOCKED"}])
    spy = _emit_spy(monkeypatch)
    for i in range(10):
        vl.round_close(ws, now=T0 + timedelta(seconds=30 * i))
    assert sum(1 for a, act in spy
               if act == "t2_queue_built") == 1, spy


# ---------- 2. real changes rebuild ------------------------------------------

def test_register_change_rebuilds(tmp_path, monkeypatch):
    ws = _ws(tmp_path, [{"id": "C-1", "status": "OPEN"}])
    spy = _emit_spy(monkeypatch)
    vl.round_close(ws, now=T0)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [{"id": "C-1", "status": "OPEN"},
                                   {"id": "C-2", "status": "BLOCKED"}]}),
        encoding="utf-8")
    vl.round_close(ws, now=T0 + timedelta(minutes=1))
    assert sum(1 for a, act in spy
               if act == "t2_queue_built") == 2              # rebuilt
    doc = json.loads(_queue_file(ws).read_text(encoding="utf-8"))
    assert [e["claim_id"] for e in doc["queue"]] == ["C-1", "C-2"]


def test_status_change_rebuilds(tmp_path, monkeypatch):
    ws = _ws(tmp_path, [{"id": "C-1", "status": "OPEN"}])
    spy = _emit_spy(monkeypatch)
    vl.round_close(ws, now=T0)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [{"id": "C-1", "status": "BLOCKED"}]}),
        encoding="utf-8")
    vl.round_close(ws, now=T0 + timedelta(minutes=1))
    assert sum(1 for a, act in spy
               if act == "t2_queue_built") == 2
    doc = json.loads(_queue_file(ws).read_text(encoding="utf-8"))
    assert doc["queue"][0]["status"] == "BLOCKED"


# ---------- 3. the stall-floor crossing IS a change --------------------------

def test_stall_floor_crossing_rebuilds(tmp_path, monkeypatch):
    """A claim crossing the stall floor changes its priority class —
    that is a real queue-shape change (the unblocking-value order depends
    on it), unlike the per-minute age churn. The claim backs on an
    mtime-controlled evidence file: FRESH at the first close (active),
    untouched while the clock crosses the floor (stalled) — the mutation
    this pin discriminates: dropping stalled/priority from the signature
    would let a real crossing be silently skipped."""
    import os
    ws = _ws(tmp_path, [{"id": "C-1", "status": "OPEN"}])
    spy = _emit_spy(monkeypatch)
    p = ws / "runs" / "C-1-verify-note.md"
    p.write_text("---\nclaim_id: C-1\n---\n\n## Overall verdict\n"
                 "passes\n", encoding="utf-8")
    stamp = (T0 - timedelta(minutes=5)).timestamp()
    os.utime(p, (stamp, stamp))                   # fresh evidence at T0
    vl.round_close(ws, now=T0)                    # active: stalled False
    doc = json.loads(_queue_file(ws).read_text(encoding="utf-8"))
    assert doc["queue"][0]["stalled"] is False
    vl.round_close(ws, now=T0 + timedelta(hours=2))   # past the 60min floor
    doc = json.loads(_queue_file(ws).read_text(encoding="utf-8"))
    assert doc["queue"][0]["stalled"] is True     # the crossing rebuilt
    assert sum(1 for a, act in spy
               if act == "t2_queue_built") == 2


# ---------- 4. the drain face keeps its semantics ----------------------------

def test_drain_keeps_semantics_and_the_gate_does_not_double_emit(
        tmp_path, monkeypatch):
    """The drain pops the head (a real consumption — the remainder loses
    the signature, so the next round-close legitimately rebuilds once)
    and the gate then holds: unchanged inputs emit nothing further. The
    pre-existing drain semantics (the rebuild restores the full queue
    until the claim settles) are preserved exactly."""
    ws = _ws(tmp_path, [{"id": "C-1", "status": "OPEN"},
                        {"id": "C-2", "status": "OPEN"}])
    spy = _emit_spy(monkeypatch)
    vl.round_close(ws, now=T0)
    out = vl.drain_t2_queue(ws, budget=1, now=T0 + timedelta(minutes=1))
    assert [e["claim_id"] for e in out["dispatched"]] == ["C-1"]
    n_after_drain = sum(1 for a, act in spy if act == "t2_queue_built")
    vl.round_close(ws, now=T0 + timedelta(minutes=2))
    assert sum(1 for a, act in spy
               if act == "t2_queue_built") == n_after_drain + 1   # one rebuild
    after = json.loads(_queue_file(ws).read_text(encoding="utf-8"))
    assert [e["claim_id"] for e in after["queue"]] == ["C-1", "C-2"]
    # and then the gate holds
    n = sum(1 for a, act in spy if act == "t2_queue_built")
    vl.round_close(ws, now=T0 + timedelta(minutes=3))
    assert sum(1 for a, act in spy if act == "t2_queue_built") == n


# ---------- 5. the first build always persists -------------------------------

def test_first_build_persists_and_emits(tmp_path, monkeypatch):
    ws = _ws(tmp_path, [{"id": "C-1", "status": "OPEN"}])
    spy = _emit_spy(monkeypatch)
    out = vl.round_close(ws, now=T0)
    assert out["built"] is True
    doc = json.loads(_queue_file(ws).read_text(encoding="utf-8"))
    assert doc["schema"] == "t2-queue/1"
    assert doc.get("sig"), "the input signature rides the doc"
    assert sum(1 for a, act in spy
               if act == "t2_queue_built") == 1
