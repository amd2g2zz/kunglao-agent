# -*- coding: utf-8 -*-
"""tests/test_claims_store_800_rollout.py — #800 R2 rollout-key
amendments (six-expert production-log panel 2026-10-23; issue #800
acceptance additions; plan v016-final-program Rev 2, Standards 11-12).

Production evidence these pins replay (SYNTHETIC rows, production
SHAPE — raw production logs never enter the repo, public-repo privacy
rule):
- arm/dispatch_id NULL on 100% of settlement rows; the settle face
  keyed everything by claim id (stores were not projections of one
  keyed ledger).
- android run 2026-10-21: a PROVEN settlement minted 03:41:02 while
  the L1 verifier REJECTed 9/9 through 03:41:52 (settlement minted
  around a failing verifier).
- the same claim re-settled 3x (terminal idempotency).
- C-005 dispatched + PROVEN with NO settlement row and NO warn (the
  silent lie).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

import claims_store  # noqa: E402


def _ws(tmp_path, claims: dict) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [{"id": cid, "status": st}
                                   for cid, st in claims.items()]}),
        encoding="utf-8")
    return ws


def _set_status(ws: Path, cid: str, status: str) -> None:
    p = ws / "claim-register.yaml"
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    for c in doc["claims"]:
        if c["id"] == cid:
            c["status"] = status
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")


def _ledger_rows(ws: Path) -> list:
    p = ws / "runs" / "dispatch-ledger.jsonl"
    if not p.is_file():
        return []
    return [json.loads(ln) for ln in
            p.read_text(encoding="utf-8").splitlines() if ln.strip()]


# --------------------------------------------------- pin 1: the keyed ledger

def test_dispatch_id_mints_to_ledger_and_rides_the_pending_row(tmp_path):
    """Amendment 1: begin_dispatch mints ONE dispatch_id that lands on
    the durable ledger (dispatched -> committed) AND foreign-keys the
    q-cell pending dispatch row (matchable by the REAL id, not the
    claim alias)."""
    from rlvr import q_cells as qc
    ws = _ws(tmp_path, {"C-1": "OPEN"})
    began = claims_store.begin_dispatch(
        ws, "C-1", "hook:worker_budget", tier=1, prompt="p", agent="a",
        method_family="static_recovery")
    assert began.ok
    did = began.journal_id
    assert did
    out = qc.record_dispatch_observation(
        ws, "envelope", envelope_meta={"method_family":
                                       "static_recovery"},
        claim="C-1", agent="a", dispatch_id=did)
    assert out["appended"] is True
    committed = claims_store.commit_dispatch(ws, "C-1")
    assert committed.ok
    rows = _ledger_rows(ws)
    assert [r["state"] for r in rows] == ["dispatched", "committed"]
    assert all(r["dispatch_id"] == did for r in rows)
    assert all(r["claim"] == "C-1" for r in rows)
    # the FK: the pending q-cell row matches by the REAL dispatch id
    match = qc._match_pending_dispatch(ws, did)
    assert match is not None
    assert str(match.get("dispatch_id") or "") == did
    latest = claims_store.latest_committed_dispatch(ws, "C-1")
    assert latest is not None and latest["dispatch_id"] == did


# ------------------------------------------- pin 2: verification ordering

def test_settlement_never_mints_around_verification(tmp_path):
    """Amendment 2 (production: settlement 03:41:02 minted while the
    verifier REJECTed through 03:41:52): a decisive settle through the
    store REFUSES without a verification reference, and REFUSES when
    the referenced verification postdates the mint."""
    ws = _ws(tmp_path, {"C-2": "IN_PROGRESS"})
    bare = claims_store.apply(ws, "C-2", "settle_proven",
                              "hook:dispatch_gate")
    assert not bare.ok
    assert "settlement-without-verification" in bare.reason
    late = claims_store.apply(ws, "C-2", "settle_proven",
                              "hook:dispatch_gate",
                              verification="verify-1",
                              verification_ts="2999-01-01T00:00:00Z")
    assert not late.ok
    assert "settlement-precedes-verification" in late.reason
    ok = claims_store.apply(ws, "C-2", "settle_proven",
                            "hook:dispatch_gate",
                            verification="verify-1",
                            verification_ts="2000-01-01T00:00:00Z")
    assert ok.ok and ok.to_status == "PROVEN"
    # both refusals left provenance rows (the audit trail)
    prov = [json.loads(ln) for ln in
            (ws / "runs" / "claims-provenance.jsonl")
            .read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len([r for r in prov if r.get("outcome") == "refused"]) == 2


def test_negative_settlement_needs_no_verification(tmp_path):
    """A decisive FAIL settlement (REFUTED) claims nothing — the
    verification guard covers only the success mints (PROVEN/VERIFIED)."""
    ws = _ws(tmp_path, {"C-2b": "IN_PROGRESS"})
    out = claims_store.apply(ws, "C-2b", "settle_refuted",
                             "hook:dispatch_gate")
    assert out.ok and out.to_status == "REFUTED"


# ---------------------------------------------- pin 3: terminal idempotent

def test_terminal_claims_are_idempotent(tmp_path):
    """Amendment 3 (production: the same claim settled 3x): a second
    decisive settle on a terminal claim is refused and the register is
    unchanged."""
    ws = _ws(tmp_path, {"C-3": "IN_PROGRESS"})
    first = claims_store.apply(ws, "C-3", "settle_proven",
                               "hook:dispatch_gate",
                               verification="verify-3",
                               verification_ts="2000-01-01T00:00:00Z")
    assert first.ok
    second = claims_store.apply(ws, "C-3", "settle_proven",
                                "hook:dispatch_gate",
                                verification="verify-3",
                                verification_ts="2000-01-01T00:00:00Z")
    assert not second.ok
    assert "illegal-transition" in second.reason
    doc = yaml.safe_load((ws / "claim-register.yaml")
                         .read_text(encoding="utf-8"))
    assert [c["status"] for c in doc["claims"] if c["id"] == "C-3"] \
        == ["PROVEN"]


# --------------------------------------------- pin 4: missing-rollout loud

def test_committed_dispatch_without_settlement_is_loud(tmp_path):
    """Amendment 4 (production C-005: dispatched + PROVEN, no
    settlement row, no warn — the silent lie): the audit emits ONE
    missing_rollout event per gap; a dispatch banked under the REAL
    dispatch id stays quiet. No-backcompat ruling: a row banked ONLY
    under the pre-R2 claim alias is a gap too (the ledger id is the
    one key)."""
    from rlvr import q_cells as qc
    ws = _ws(tmp_path, {"C-4": "OPEN", "C-5": "OPEN"})
    dids = {}
    for cid in ("C-4", "C-5"):
        began = claims_store.begin_dispatch(
            ws, cid, "hook:worker_budget", tier=1, prompt="p",
            agent="a", method_family="static_recovery")
        assert began.ok
        assert claims_store.commit_dispatch(ws, cid).ok
        dids[cid] = began.journal_id
    # C-5: banked under the REAL dispatch id -> quiet
    qc.record_dispatch_observation(
        ws, "envelope", envelope_meta={"method_family":
                                       "static_recovery"},
        claim="C-5", agent="a", dispatch_id=dids["C-5"])
    assert qc.observe_settlement(
        ws, dids["C-5"], 1.0)["appended"] is True
    _set_status(ws, "C-4", "PROVEN")
    _set_status(ws, "C-5", "PROVEN")
    gaps = claims_store.audit_missing_rollouts(ws)
    assert [g["claim"] for g in gaps] == ["C-4"]
    logs = ws / "runs" / "logs"
    rows = [json.loads(ln) for p in sorted(logs.glob("kunglao-*.jsonl"))
            for ln in p.read_text(encoding="utf-8").splitlines()
            if ln.strip()]
    events = [r for r in rows if r.get("action") == "missing_rollout"]
    assert len(events) == 1
    assert events[0].get("claim") == "C-4"


def test_alias_banked_row_is_still_a_gap_no_backcompat(tmp_path):
    """No-backcompat ruling (2026-09-01): the dispatch-ledger id is
    the ONE key. A settlement banked ONLY under the pre-R2 claim-id
    alias (no dispatch_id on the row) does not quiet the audit — the
    gap stands and is loud."""
    from rlvr import q_cells as qc
    ws = _ws(tmp_path, {"C-8": "OPEN"})
    began = claims_store.begin_dispatch(
        ws, "C-8", "hook:worker_budget", tier=1, prompt="p",
        agent="a", method_family="static_recovery")
    assert began.ok
    assert claims_store.commit_dispatch(ws, "C-8").ok
    # pre-R2 shape: pending row + banked row carry NO dispatch_id
    qc.record_dispatch_observation(
        ws, "envelope", envelope_meta={"method_family":
                                       "static_recovery"},
        claim="C-8", agent="a")
    assert qc.observe_settlement(ws, "C-8", 1.0)["appended"] is True
    _set_status(ws, "C-8", "PROVEN")
    gaps = claims_store.audit_missing_rollouts(ws)
    assert [g["claim"] for g in gaps] == ["C-8"]


def test_inflight_dispatch_is_not_a_gap(tmp_path):
    """A committed dispatch whose claim is still OPEN owes no
    settlement yet — the audit stays quiet (no false alarm)."""
    ws = _ws(tmp_path, {"C-6": "OPEN"})
    began = claims_store.begin_dispatch(
        ws, "C-6", "hook:worker_budget", tier=1, prompt="p",
        agent="a", method_family="static_recovery")
    assert began.ok
    assert claims_store.commit_dispatch(ws, "C-6").ok
    assert claims_store.audit_missing_rollouts(ws) == []


def test_missing_rollout_repetition_is_bounded_and_escalates(tmp_path):
    """Standard 11 (bounded repetition + ownership transfer): a
    persistent gap emits exactly MISSING_ROLLOUT_REPEAT_LIMIT events —
    the last one escalated — then degrades to emit-silence while every
    audit pass still reports the gap. Repetition is not escalation
    (the production 392-warn lesson)."""
    ws = _ws(tmp_path, {"C-7": "OPEN"})
    began = claims_store.begin_dispatch(
        ws, "C-7", "hook:worker_budget", tier=1, prompt="p",
        agent="a", method_family="static_recovery")
    assert began.ok
    assert claims_store.commit_dispatch(ws, "C-7").ok
    _set_status(ws, "C-7", "PROVEN")
    limit = claims_store.MISSING_ROLLOUT_REPEAT_LIMIT
    for _ in range(limit + 2):
        gaps = claims_store.audit_missing_rollouts(ws)
        assert [g["claim"] for g in gaps] == ["C-7"]  # always reported
    logs = ws / "runs" / "logs"
    rows = [json.loads(ln) for p in sorted(logs.glob("kunglao-*.jsonl"))
            for ln in p.read_text(encoding="utf-8").splitlines()
            if ln.strip()]
    events = [json.loads(r.get("detail") or "{}") for r in rows
              if r.get("action") == "missing_rollout"]
    assert len(events) == limit
    assert [e.get("occurrence") for e in events] == list(
        range(1, limit + 1))
    assert events[-1].get("escalated") is True
