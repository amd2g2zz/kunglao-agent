# -*- coding: utf-8 -*-
"""#49 dispatch ROI settlement — intent contract + entropy-gain admission gate.

RED-first tests pin the contract before implementation:

- record_intent gate (owner ruling 3): an intent that cannot name WHICH
  uncertainty it eliminates is non-compliant -> {ok: False,
  reason: MISSING_UNCERTAINTY}. This PR exposes the gate as a data channel;
  wiring enforcement into dispatch_gate stays out of scope.
- record_intent valid -> idempotent append to runs/roi-intents.jsonl.
- settle_intent (owner ruling 2): outcome is judged ONLY against the intent
  declared at dispatch time. Zero facts != negative ROI — early recon
  dispatched with a map intent is POSITIVE once a map artifact exists, even
  with a zero fact delta.
- Owner ruling 1: value = method x context x outcome — every settlement row
  carries the full triple, never a per-method value label.
"""
import json
from pathlib import Path

import pytest

import roi_settlement as roi


def _read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _record(ws, claim_id="C-1", **kw):
    args = dict(method="ghidra-light", context_tags=["re", "vm"],
                uncertainty="which config builder reconstructs the header",
                expected_artifact="map")
    args.update(kw)
    return roi.record_intent(ws, claim_id, **args)


# ---------- record_intent: entropy-gain admission gate (ruling 3) ----------

class TestRecordIntentGate:
    def test_missing_uncertainty_rejected(self, tmp_path):
        """Empty uncertainty -> ok False + MISSING_UNCERTAINTY, nothing written."""
        res = _record(tmp_path, uncertainty="")
        assert res["ok"] is False
        assert res["reason"] == roi.MISSING_UNCERTAINTY
        assert not roi.intents_path(tmp_path).exists()

    def test_whitespace_uncertainty_rejected(self, tmp_path):
        """Whitespace-only uncertainty is not a named uncertainty."""
        res = _record(tmp_path, uncertainty="   ")
        assert res["ok"] is False
        assert res["reason"] == roi.MISSING_UNCERTAINTY

    def test_none_uncertainty_rejected(self, tmp_path):
        res = _record(tmp_path, uncertainty=None)
        assert res["ok"] is False
        assert res["reason"] == roi.MISSING_UNCERTAINTY


# ---------- record_intent: valid append + idempotency ----------

class TestRecordIntentAppend:
    def test_valid_intent_appends(self, tmp_path):
        res = _record(tmp_path)
        assert res["ok"] is True
        rec = res["record"]
        assert rec["claim_id"] == "C-1"
        assert rec["method"] == "ghidra-light"
        assert rec["context_tags"] == ["re", "vm"]
        assert rec["uncertainty"] == \
            "which config builder reconstructs the header"
        assert rec["expected_artifact"] == "map"
        assert rec["ts"]
        assert roi.intents_path(tmp_path).exists()

    def test_valid_intent_idempotent(self, tmp_path):
        """Same claim + same declared intent twice -> one ledger line."""
        first = _record(tmp_path)
        second = _record(tmp_path)
        assert first["ok"] is True and second["ok"] is True
        assert len(_read_jsonl(roi.intents_path(tmp_path))) == 1

    def test_distinct_claims_both_appended(self, tmp_path):
        _record(tmp_path, claim_id="C-1")
        _record(tmp_path, claim_id="C-2")
        assert len(_read_jsonl(roi.intents_path(tmp_path))) == 2

    def test_has_intent(self, tmp_path):
        assert roi.has_intent(tmp_path, "C-1") is False
        _record(tmp_path, claim_id="C-1")
        assert roi.has_intent(tmp_path, "C-1") is True
        assert roi.has_intent(tmp_path, "C-9") is False


# ---------- settle_intent: outcome-vs-intent attribution (ruling 2) ----------

class TestSettleIntent:
    def test_settle_without_intent_is_no_intent(self, tmp_path):
        res = roi.settle_intent(tmp_path, "C-404", {"verdict": "passes"})
        assert res["ok"] is False
        assert res["reason"] == roi.NO_INTENT

    def test_artifact_match_positive_with_zero_facts(self, tmp_path):
        """Ruling 2 anchor: early recon, intent=map, zero facts -> POSITIVE."""
        _record(tmp_path, claim_id="C-1", expected_artifact="map",
                uncertainty="what does the territory look like")
        outcome = {"verdict": "", "artifacts": ["runs/recon-map.md"],
                   "facts_written": 0}
        res = roi.settle_intent(tmp_path, "C-1", outcome)
        assert res["ok"] is True
        s = res["settlement"]
        assert s["intent_met"] is True
        assert s["uncertainty_eliminated"] is True
        assert s["roi_class"] == "POSITIVE"
        assert "artifact_match" in s["signals"]

    def test_partial_artifact_token_match(self, tmp_path):
        """Expected-artifact type matches as a case-insensitive token."""
        _record(tmp_path, claim_id="C-1", expected_artifact="Report")
        res = roi.settle_intent(tmp_path, "C-1",
                                {"artifacts": ["facts/F001-report.md"]})
        assert res["settlement"]["roi_class"] == "POSITIVE"

    def test_failing_verdict_negative(self, tmp_path):
        _record(tmp_path, claim_id="C-1")
        res = roi.settle_intent(tmp_path, "C-1", {"verdict": "fails"})
        assert res["settlement"]["intent_met"] is False
        assert res["settlement"]["roi_class"] == "NEGATIVE"

    def test_redteam_refuted_negative_confirmed_positive(self, tmp_path):
        _record(tmp_path, claim_id="C-1")
        _record(tmp_path, claim_id="C-2")
        assert roi.settle_intent(tmp_path, "C-1",
                                 {"verdict": "REFUTED"})["settlement"][
            "roi_class"] == "NEGATIVE"
        assert roi.settle_intent(tmp_path, "C-2",
                                 {"verdict": "CONFIRMED"})["settlement"][
            "roi_class"] == "POSITIVE"

    def test_passes_verdict_positive(self, tmp_path):
        _record(tmp_path, claim_id="C-1")
        res = roi.settle_intent(tmp_path, "C-1", {"verdict": "passes"})
        assert res["settlement"]["roi_class"] == "POSITIVE"

    def test_partial_verdict_neutral(self, tmp_path):
        _record(tmp_path, claim_id="C-1")
        res = roi.settle_intent(tmp_path, "C-1", {"verdict": "partial"})
        assert res["settlement"]["intent_met"] is None
        assert res["settlement"]["roi_class"] == "NEUTRAL"

    def test_empty_outcome_unresolved(self, tmp_path):
        """Nothing comparable observed yet -> UNRESOLVED (never NEGATIVE:
        zero output is not a negative verdict, ruling 2)."""
        _record(tmp_path, claim_id="C-1")
        res = roi.settle_intent(tmp_path, "C-1", {})
        assert res["settlement"]["intent_met"] is None
        assert res["settlement"]["roi_class"] == "UNRESOLVED"

    def test_hypotheses_resolved_signal(self, tmp_path):
        _record(tmp_path, claim_id="C-1")
        res = roi.settle_intent(tmp_path, "C-1", {"hypotheses_resolved": 2})
        assert res["settlement"]["roi_class"] == "POSITIVE"
        assert "hypotheses_resolved" in res["settlement"]["signals"]

    def test_claims_closed_signal(self, tmp_path):
        _record(tmp_path, claim_id="C-1")
        res = roi.settle_intent(tmp_path, "C-1", {"claims_closed": 1})
        assert res["settlement"]["roi_class"] == "POSITIVE"
        assert "claims_closed" in res["settlement"]["signals"]

    def test_fact_count_is_never_a_signal(self, tmp_path):
        """Ruling 3: uncertainty eliminated, NOT fact count. A big fact delta
        with no named-uncertainty signal and no verdict does NOT meet intent."""
        _record(tmp_path, claim_id="C-1")
        res = roi.settle_intent(tmp_path, "C-1", {"facts_written": 42})
        assert res["settlement"]["roi_class"] == "UNRESOLVED"
        assert res["settlement"]["signals"] == []


# ---------- settlement persistence: the data layer for #50/#59 ----------

class TestSettlementPersistence:
    def test_settlement_row_persisted(self, tmp_path):
        _record(tmp_path, claim_id="C-1")
        roi.settle_intent(tmp_path, "C-1", {"verdict": "passes"})
        rows = _read_jsonl(roi.settlements_path(tmp_path))
        assert len(rows) == 1
        assert rows[0]["claim_id"] == "C-1"
        assert rows[0]["roi_class"] == "POSITIVE"
        assert rows[0]["ts"]

    def test_settlement_row_carries_method_context_outcome_triple(self, tmp_path):
        """Ruling 1: value = method x context x outcome — the full triple."""
        _record(tmp_path, claim_id="C-1", method="web-re",
                context_tags=["web", "re"])
        roi.settle_intent(tmp_path, "C-1",
                          {"verdict": "passes", "checker": "verify-note"})
        row = _read_jsonl(roi.settlements_path(tmp_path))[0]
        assert row["intent"]["method"] == "web-re"
        assert row["intent"]["context_tags"] == ["web", "re"]
        assert row["intent"]["uncertainty"]
        assert row["intent"]["expected_artifact"] == "map"
        assert row["outcome"] == {"verdict": "passes",
                                  "checker": "verify-note"}

    def test_settlement_idempotent_by_claim_and_outcome(self, tmp_path):
        _record(tmp_path, claim_id="C-1")
        first = roi.settle_intent(tmp_path, "C-1", {"verdict": "passes"})
        second = roi.settle_intent(tmp_path, "C-1", {"verdict": "passes"})
        assert first["ok"] is True and second["ok"] is True
        assert second["duplicate"] is True
        assert len(_read_jsonl(roi.settlements_path(tmp_path))) == 1

    def test_changed_outcome_settles_again(self, tmp_path):
        """An evolving verdict (partial -> passes) is a second, distinct
        settlement — mirrors outcome_capture's claim|checker|result key."""
        _record(tmp_path, claim_id="C-1")
        roi.settle_intent(tmp_path, "C-1", {"verdict": "partial"})
        roi.settle_intent(tmp_path, "C-1", {"verdict": "passes"})
        rows = _read_jsonl(roi.settlements_path(tmp_path))
        assert sorted(r["roi_class"] for r in rows) == ["NEUTRAL", "POSITIVE"]

    def test_latest_intent_wins(self, tmp_path):
        """A re-declared (corrected) intent is what settlement judges against."""
        _record(tmp_path, claim_id="C-1", expected_artifact="map")
        _record(tmp_path, claim_id="C-1", expected_artifact="fqa",
                uncertainty="does the FQA list match recovered strings")
        res = roi.settle_intent(tmp_path, "C-1",
                                {"artifacts": ["facts/F001-fqa.md"]})
        assert res["settlement"]["intent"]["expected_artifact"] == "fqa"
        assert res["settlement"]["roi_class"] == "POSITIVE"

    def test_malformed_intent_lines_skipped(self, tmp_path):
        """Tolerant read: junk lines in the intents file never crash settle."""
        roi.record_intent(tmp_path, "C-1", method="m", context_tags=[],
                          uncertainty="u", expected_artifact="")
        p = roi.intents_path(tmp_path)
        p.write_text(p.read_text(encoding="utf-8") + "\nnot json\n{broken\n",
                     encoding="utf-8")
        res = roi.settle_intent(tmp_path, "C-1", {"verdict": "passes"})
        assert res["ok"] is True

    def test_missing_uncertainty_constant(self, tmp_path):
        """The gate reason is the frozen MISSING_UNCERTAINTY token."""
        assert roi.MISSING_UNCERTAINTY == "MISSING_UNCERTAINTY"
        with pytest.raises(AttributeError):
            roi.NOT_A_REAL_CONSTANT  # noqa: B018  (module surface guard)


# ---------- outcome_capture integration (group 2: settlement wiring) ----------

class TestOutcomeCaptureWiring:
    """capture() settles claims whose intent exists; fail-open otherwise."""

    def _seed_verify(self, ws, claim_id="C-1", verdict="passes"):
        runs = ws / "runs"
        runs.mkdir(exist_ok=True)
        (runs / "2026-08-11T00-00-00-verify-01.md").write_text(
            f"---\nclaim_id: {claim_id}\n---\n\n## Overall verdict\n{verdict}\n",
            encoding="utf-8")

    def test_capture_with_intent_settles(self, tmp_path):
        """verify-note result + existing intent -> settled row appears."""
        import outcome_capture as oc
        _record(tmp_path, claim_id="C-1",
                uncertainty="which config builder reconstructs the header")
        self._seed_verify(tmp_path, "C-1", "passes")
        added = oc.capture(tmp_path)
        assert added == 1
        rows = _read_jsonl(roi.settlements_path(tmp_path))
        assert len(rows) == 1
        assert rows[0]["claim_id"] == "C-1"
        assert rows[0]["roi_class"] == "POSITIVE"
        assert rows[0]["outcome"]["verdict"] == "passes"

    def test_capture_without_intents_is_noop(self, tmp_path):
        """Zero intents -> no settlements file, capture unchanged (old
        workspaces unaffected)."""
        import outcome_capture as oc
        self._seed_verify(tmp_path, "C-1", "passes")
        assert oc.capture(tmp_path) == 1
        assert oc.read_outcome_rows(tmp_path)[0]["result"] == "passes"
        assert not roi.settlements_path(tmp_path).exists()

    def test_capture_fail_open_on_settlement_error(self, tmp_path, monkeypatch):
        """A settlement crash must never break capture (fail-open)."""
        import outcome_capture as oc
        _record(tmp_path, claim_id="C-1")

        def _boom(*a, **k):
            raise RuntimeError("settlement exploded")
        monkeypatch.setattr(roi, "settle_intent", _boom)
        self._seed_verify(tmp_path, "C-1", "passes")
        assert oc.capture(tmp_path) == 1
        assert len(oc.read_outcome_rows(tmp_path)) == 1

    def test_capture_redteam_result_settles(self, tmp_path):
        """red-team CONFIRMED settles POSITIVE through the same path."""
        import outcome_capture as oc
        runs = tmp_path / "runs"
        runs.mkdir()
        (runs / "verify-redteam-C-7.md").write_text(
            "RED-TEAM VERDICT: CONFIRMED\n\ntarget: C-7\n", encoding="utf-8")
        _record(tmp_path, claim_id="C-7")
        oc.capture(tmp_path)
        rows = _read_jsonl(roi.settlements_path(tmp_path))
        assert rows[0]["roi_class"] == "POSITIVE"

    def test_capture_idempotent_no_duplicate_settlements(self, tmp_path):
        """Re-running capture (already-seen outcome) does not re-settle."""
        import outcome_capture as oc
        _record(tmp_path, claim_id="C-1")
        self._seed_verify(tmp_path, "C-1", "passes")
        oc.capture(tmp_path)
        oc.capture(tmp_path)
        assert len(_read_jsonl(roi.settlements_path(tmp_path))) == 1
