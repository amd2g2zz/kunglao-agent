# -*- coding: utf-8 -*-
"""tests/test_signals_stream_12.py — the signal stream (runs/signals.jsonl).

The 2026-09-04 ruling: outcome signals are primary; "route signals as
text vs act on them" converges — delivered facts land as
structured rows in the append-only stream (runs/signals.jsonl) instead of
only text annotations (fact-file prose, claim-register notes, worker-status
lines). The Δ-estimator reads THIS stream, never the orchestrator's memory.

Producers wired in this slice (all fail-open):
  - kunglao_record.record_event: fact_written -> deliver, fact_verified -> verify
  - hooks/dispatch_gate main() ALLOW tail: dispatch
  - rollup.run_rollup: red-team CONFIRMED verdict file with DIFF markers
    -> confirmed_with_diff (substantive-DIFF count rides the row)
Toss is DERIVED at read time: a dispatch whose claim never sees a later
deliver row (delivery not yet reconciled — the small per-round penalty input).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import signals_stream as ss  # noqa: E402
from kunglao_record import record_event  # noqa: E402


def test_append_and_read_roundtrip(tmp_path):
    ok = ss.append(tmp_path, ss.KIND_DELIVER, claim="C-1", fact="F001")
    assert ok is True
    rows = ss.read(tmp_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == "deliver"
    assert row["claim"] == "C-1"
    assert row["fact"] == "F001"
    assert row["ts"]  # stamped


def test_stream_is_append_only_jsonl(tmp_path):
    ss.append(tmp_path, ss.KIND_DISPATCH, claim="C-1")
    ss.append(tmp_path, ss.KIND_DELIVER, claim="C-1")
    raw = (tmp_path / "runs" / "signals.jsonl").read_text(encoding="utf-8")
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    assert len(lines) == 2
    assert all(isinstance(json.loads(ln), dict) for ln in lines)


def test_delivery_event_lands_a_row(tmp_path):
    """THE pin: a worker delivery event (fact_written through the M4 RECORD
    path) lands a structured row — the text-annotation-only routing is gone."""
    (tmp_path / "claim-register.yaml").write_text(
        "claims:\n- id: C-1\n  status: OPEN\n", encoding="utf-8")
    seq = record_event(tmp_path, {"source_module": "test",
                                  "event_type": "fact_written",
                                  "payload": {"claim_id": "C-1",
                                              "fact_id": "F001"}})
    assert seq == 1
    rows = ss.read(tmp_path)
    assert len(rows) == 1
    assert rows[0]["kind"] == ss.KIND_DELIVER
    assert rows[0]["claim"] == "C-1"


def test_duplicate_delivery_does_not_double_append(tmp_path):
    (tmp_path / "claim-register.yaml").write_text(
        "claims:\n- id: C-1\n  status: OPEN\n", encoding="utf-8")
    ev = {"source_module": "test", "event_type": "fact_written",
          "payload": {"claim_id": "C-1", "fact_id": "F001"}}
    record_event(tmp_path, ev)
    record_event(tmp_path, ev)  # idempotent ledger write
    assert len(ss.read(tmp_path)) == 1


def test_fact_verified_lands_verify_row(tmp_path):
    (tmp_path / "claim-register.yaml").write_text(
        "claims:\n- id: C-1\n  status: OPEN\n", encoding="utf-8")
    record_event(tmp_path, {"source_module": "test",
                            "event_type": "fact_verified",
                            "payload": {"claim_id": "C-1"}})
    rows = ss.read(tmp_path)
    assert rows[0]["kind"] == ss.KIND_VERIFY


def test_tolerant_read_skips_dirty_rows(tmp_path):
    (tmp_path / "runs").mkdir()
    p = tmp_path / "runs" / "signals.jsonl"
    p.write_text('{"kind": "deliver", "claim": "C-1"}\nnot json at all\n'
                 '[1, 2]\n{"kind": "verify", "claim": "C-2"}\n',
                 encoding="utf-8")
    rows = ss.read(tmp_path)
    assert [r["kind"] for r in rows] == ["deliver", "verify"]


def test_penalty_counts_window_and_toss(tmp_path):
    """The negative-reward penalty inputs: dispatch / verify / confirmed_with_diff /
    toss counts over an append-order window (machine-independent — no wall
    clock in the windowing)."""
    ss.append(tmp_path, ss.KIND_DISPATCH, claim="C-1")
    ss.append(tmp_path, ss.KIND_DELIVER, claim="C-1")   # C-1 reconciled
    ss.append(tmp_path, ss.KIND_DISPATCH, claim="C-2")  # C-2 never delivered
    ss.append(tmp_path, ss.KIND_VERIFY, claim="C-1")
    ss.append(tmp_path, ss.KIND_CONFIRMED_WITH_DIFF, claim="C-1", diffs=1)

    full = ss.penalty_counts(tmp_path, after_rows=0)
    assert full == {"dispatch": 2, "verify": 1, "confirmed_with_diff": 1,
                    "toss": 1}  # C-2's dispatch is unresolved -> toss
    # window: only rows appended after the first two
    tail = ss.penalty_counts(tmp_path, after_rows=2)
    assert tail["dispatch"] == 1
    assert tail["verify"] == 1
    assert tail["toss"] == 1


def test_count_rows_cursor(tmp_path):
    assert ss.count_rows(tmp_path) == 0
    ss.append(tmp_path, ss.KIND_DISPATCH, claim="C-1")
    ss.append(tmp_path, ss.KIND_DISPATCH, claim="C-2")
    assert ss.count_rows(tmp_path) == 2


def test_append_never_raises_on_blocked_path(tmp_path):
    """Fail-open posture (issue 275 class): a write failure degrades to
    False, never an exception into the producer's path."""
    blocker = tmp_path / "runs"
    blocker.write_text("not a dir\n", encoding="utf-8")  # mkdir will fail
    assert ss.append(tmp_path, ss.KIND_DELIVER, claim="C-1") is False


def test_append_never_raises_on_unserializable_field(tmp_path):
    """The NEVER-raises contract covers ANY failure, not just OSError: an
    unserializable extra field (json.dumps TypeError) degrades to False."""
    assert ss.append(tmp_path, ss.KIND_DISPATCH, claim="C-1",
                     extra=object()) is False
    assert ss.read(tmp_path) == []  # nothing half-landed


def test_append_once_is_idempotent_on_signal_id(tmp_path):
    """The record_event idiom on the stream: the same signal_id lands
    exactly one row; a changed identity (evolving verdict, different diff
    count) lands again."""
    assert ss.append_once(tmp_path, ss.KIND_CONFIRMED_WITH_DIFF, "sid-1",
                          claim="C-1", diffs=2, source="f.md") is True
    assert ss.append_once(tmp_path, ss.KIND_CONFIRMED_WITH_DIFF, "sid-1",
                          claim="C-1", diffs=2, source="f.md") is True
    assert len(ss.read(tmp_path)) == 1
    # changed identity -> lands again
    assert ss.append_once(tmp_path, ss.KIND_CONFIRMED_WITH_DIFF, "sid-2",
                          claim="C-1", diffs=3, source="f.md") is True
    assert len(ss.read(tmp_path)) == 2
    assert ss.landed_signal_ids(tmp_path) == {"sid-1", "sid-2"}
    assert ss.landed_signal_ids(tmp_path, ss.KIND_DELIVER) == set()


def test_rollup_confirmed_with_diff_lands_row(tmp_path):
    """The red-team face: a CONFIRMED verdict file carrying DIFF markers
    lands a confirmed_with_diff row with the substantive-DIFF count when
    the terminal rollup captures it."""
    import rollup
    (tmp_path / "claim-register.yaml").write_text(
        "claims:\n- id: C-1\n  status: OPEN\n", encoding="utf-8")
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "verify-redteam-C-1.md").write_text(
        "# Red-team verification: C-1\n\nRED-TEAM VERDICT: CONFIRMED\n\n"
        "## DIFF-1\n\nmaker omitted the identity-token TTL subsystem\n"
        "## DIFF-2\n\nsecond divergence\n",
        encoding="utf-8")
    # claim must be terminal for the rollup to fire
    (tmp_path / "claim-register.yaml").write_text(
        "claims:\n- id: C-1\n  status: PROVEN\n", encoding="utf-8")
    rollup.run_rollup(tmp_path, "C-1", "PROVEN")
    rows = [r for r in ss.read(tmp_path)
            if r["kind"] == ss.KIND_CONFIRMED_WITH_DIFF]
    assert len(rows) == 1
    assert rows[0]["claim"] == "C-1"
    assert rows[0]["diffs"] == 2


def test_rollup_reglob_of_same_verdict_lands_no_second_row(tmp_path):
    """The reviewer repro, half: a later rollup re-globs ALL
    verify-redteam-*.md — the same verdict file must not land twice even
    when the capture face itself is re-entered directly (the rollup-level
    (claim, status) guard bypassed)."""
    import rollup
    (tmp_path / "claim-register.yaml").write_text(
        "claims:\n- id: C-1\n  status: PROVEN\n", encoding="utf-8")
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "verify-redteam-C-1.md").write_text(
        "RED-TEAM VERDICT: CONFIRMED\n\n## DIFF-1\n\nsubstantive gap\n",
        encoding="utf-8")
    assert rollup._capture_confirmed_with_diff(tmp_path, "C-2") == 1
    assert rollup._capture_confirmed_with_diff(tmp_path, "C-2") == 1
    rows = [r for r in ss.read(tmp_path)
            if r["kind"] == ss.KIND_CONFIRMED_WITH_DIFF]
    assert len(rows) == 1


def test_two_rollups_two_verdicts_exactly_two_rows(tmp_path):
    """The reviewer repro: C-1 rolls up (1 row) -> C-2 rolls up (its own
    verdict) — the C-1 verdict must NOT re-land. Two verdict files across
    two fired rollups -> exactly 2 rows total, and the full window counts
    each once."""
    import rollup
    (tmp_path / "claim-register.yaml").write_text(
        "claims:\n- id: C-1\n  status: PROVEN\n"
        "- id: C-2\n  status: PROVEN\n", encoding="utf-8")
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "verify-redteam-C-1.md").write_text(
        "claim: C-1\nRED-TEAM VERDICT: CONFIRMED\n\n## DIFF-1\n\nsubstantive gap one\n",
        encoding="utf-8")
    (tmp_path / "runs" / "verify-redteam-C-2.md").write_text(
        "claim: C-2\nRED-TEAM VERDICT: CONFIRMED\n\n## DIFF-1\n\nsubstantive gap two\n"
        "## DIFF-2\n\nsubstantive gap three\n",
        encoding="utf-8")
    rollup.run_rollup(tmp_path, "C-1", "PROVEN")
    rollup.run_rollup(tmp_path, "C-2", "PROVEN")
    rows = [r for r in ss.read(tmp_path)
            if r["kind"] == ss.KIND_CONFIRMED_WITH_DIFF]
    assert len(rows) == 2
    assert sorted(r["claim"] for r in rows) == ["C-1", "C-2"]
    assert sorted(r["diffs"] for r in rows) == [1, 2]
    # the full stream window counts each verdict exactly once
    assert ss.penalty_counts(tmp_path, after_rows=0)[
        "confirmed_with_diff"] == 2


def test_diff_prose_mentions_do_not_count(tmp_path):
    """The DIFF marker is LINE-ANCHORED (item lead, optional heading/bullet
    prefix): mid-sentence prose mentions ('no DIFF found', 'a DIFF, not a
    nitpick') are not divergences. A CONFIRMED verdict with zero DIFF
    items is a clean pass -> NO row (the kind is confirmed_WITH_DIFF)."""
    import rollup
    (tmp_path / "claim-register.yaml").write_text(
        "claims:\n- id: C-1\n  status: PROVEN\n", encoding="utf-8")
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "verify-redteam-C-1.md").write_text(
        "RED-TEAM VERDICT: CONFIRMED\n\n"
        "checked twice, no DIFF found anywhere\n"
        "a DIFF, not a nitpick, would have been reported\n"
        "SELF-CONSISTENCY: PASS (both paths expose a hole (DIFF))\n",
        encoding="utf-8")
    rollup.run_rollup(tmp_path, "C-1", "PROVEN")
    assert ss.read(tmp_path) == []


def test_diff_item_leads_count_once_each(tmp_path):
    """The anchored shapes the red-team contract actually emits: markdown
    heading, bullet item, numbered item, bare line lead."""
    import rollup
    (tmp_path / "claim-register.yaml").write_text(
        "claims:\n- id: C-1\n  status: PROVEN\n", encoding="utf-8")
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "verify-redteam-C-1.md").write_text(
        "RED-TEAM VERDICT: CONFIRMED\n\n"
        "## DIFF-1 heading shape\n"
        "- DIFF: bullet shape\n"
        "1. DIFF: numbered shape\n"
        "DIFF-4: bare lead shape\n",
        encoding="utf-8")
    rollup.run_rollup(tmp_path, "C-1", "PROVEN")
    rows = [r for r in ss.read(tmp_path)
            if r["kind"] == ss.KIND_CONFIRMED_WITH_DIFF]
    assert len(rows) == 1
    assert rows[0]["diffs"] == 4
