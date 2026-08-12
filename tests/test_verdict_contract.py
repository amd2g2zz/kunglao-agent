"""tests/test_verdict_contract.py -- issue #110 B4-6 verdict schema guard tests.

Validates that:
1. The verdict-output JSON schema exists and enforces the v11 analysis_verdict shape.
2. Old-shape regression guards: payloads with 'classification' or 'attribution' keys are rejected.
3. Fixture-based coverage: all-PQs-answered, missing-citing-fact, PROVEN-INITIAL,
   contradiction detection, model_selection C0b.

Consumed via conftest.py's contract_validator("verdict-output", obj).
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone

import pytest


# ---------------------------------------------------------------------------
# Helpers: build valid verdict payloads
# ---------------------------------------------------------------------------

_ISO_NOW = datetime.now(timezone.utc).isoformat()

_BASE_VERDICT: dict = {
    "_meta": {
        "source": "verdict-scorer",
        "schema_version": "2026-08-12-v11",
        "queried_at": _ISO_NOW,
        "methodology": "task_spec.primary_questions coverage + fact-citation validity",
    },
    "sample_sha256": "a" * 64,
    "analysis_verdict": {
        "complete": True,
        "correct": True,
        "primary_questions": [],
        "unresolved": [],
        "contradictions": [],
        "degraded": [],
    },
    "self_audit": {
        "evidence_strength": "strong",
        "ignored_evidence": [],
        "open_questions": [],
    },
}


def _pq(id: str, answered: bool, cited_fact: str | None = None,
        confidence_band: str | None = None, gap: str | None = None) -> dict:
    """Build a single primary_question entry."""
    return {
        "id": id,
        "answered": answered,
        "cited_fact": cited_fact,
        "confidence_band": confidence_band,
        "gap": gap,
    }


def _make_verdict(**overrides) -> dict:
    """Deep-copy _BASE_VERDICT and apply overrides at the analysis_verdict level."""
    v = copy.deepcopy(_BASE_VERDICT)
    av = v["analysis_verdict"]
    for key, val in overrides.items():
        av[key] = val
    return v


# ---------------------------------------------------------------------------
# (1) Schema exists and loads
# ---------------------------------------------------------------------------


class TestSchemaExists:
    """The verdict-output schema file must exist and be loadable."""

    def test_schema_loads(self, contract_validator) -> None:
        """contract_validator can load verdict-output schema (no crash)."""
        # This will fail with "schema file missing" if verdict-output.json doesn't exist
        contract_validator("verdict-output", _BASE_VERDICT)


# ---------------------------------------------------------------------------
# (2) Old-shape regression guards
# ---------------------------------------------------------------------------


class TestOldShapeRejected:
    """Payloads containing deleted-surface keys (classification, attribution)
    must be rejected by the schema validator."""

    def test_classification_key_rejected(self, contract_validator) -> None:
        """A payload with a top-level 'classification' key must fail validation."""
        payload = copy.deepcopy(_BASE_VERDICT)
        payload["classification"] = "malicious"
        with pytest.raises(AssertionError, match="schema.*violations"):
            contract_validator("verdict-output", payload)

    def test_attribution_key_rejected(self, contract_validator) -> None:
        """A payload with a top-level 'attribution' key must fail validation."""
        payload = copy.deepcopy(_BASE_VERDICT)
        payload["attribution"] = {"named_actor": "APT123"}
        with pytest.raises(AssertionError, match="schema.*violations"):
            contract_validator("verdict-output", payload)

    def test_classification_inside_analysis_verdict_rejected(
        self, contract_validator
    ) -> None:
        """A 'classification' key inside analysis_verdict must also fail."""
        payload = copy.deepcopy(_BASE_VERDICT)
        payload["analysis_verdict"]["classification"] = "benign"
        with pytest.raises(AssertionError, match="schema.*violations"):
            contract_validator("verdict-output", payload)

    def test_attribution_inside_analysis_verdict_rejected(
        self, contract_validator
    ) -> None:
        """An 'attribution' key inside analysis_verdict must also fail."""
        payload = copy.deepcopy(_BASE_VERDICT)
        payload["analysis_verdict"]["attribution"] = "APT123"
        with pytest.raises(AssertionError, match="schema.*violations"):
            contract_validator("verdict-output", payload)


# ---------------------------------------------------------------------------
# (3) Fixture: all PQs PROVEN-FULL -> complete: true, unresolved: []
# ---------------------------------------------------------------------------


class TestAllPqsAnswered:
    """When all primary_questions have PROVEN-FULL cited facts,
    verdict must have complete=true and unresolved=[]."""

    @pytest.fixture
    def complete_verdict(self) -> dict:
        return _make_verdict(
            primary_questions=[
                _pq("q1", True, "F010", "PROVEN-FULL", None),
                _pq("q2", True, "F020", "PROVEN-FULL", None),
            ],
        )

    def test_complete_true(self, contract_validator, complete_verdict) -> None:
        assert complete_verdict["analysis_verdict"]["complete"] is True
        contract_validator("verdict-output", complete_verdict)

    def test_unresolved_empty(self, contract_validator, complete_verdict) -> None:
        assert complete_verdict["analysis_verdict"]["unresolved"] == []
        contract_validator("verdict-output", complete_verdict)


# ---------------------------------------------------------------------------
# (4) Fixture: 1 PQ no citing fact -> complete: false + PQ in unresolved
# ---------------------------------------------------------------------------


class TestMissingCitingFact:
    """When a primary_question has no citing fact, verdict must have
    complete=false and that PQ in unresolved[]."""

    @pytest.fixture
    def incomplete_verdict(self) -> dict:
        return _make_verdict(
            complete=False,
            primary_questions=[
                _pq("q1", True, "F010", "PROVEN-FULL", None),
                _pq("q2", False, None, None, "no answering claim"),
            ],
            unresolved=["q2"],
        )

    def test_complete_false(self, contract_validator, incomplete_verdict) -> None:
        assert incomplete_verdict["analysis_verdict"]["complete"] is False
        contract_validator("verdict-output", incomplete_verdict)

    def test_unresolved_contains_q2(self, contract_validator, incomplete_verdict) -> None:
        assert "q2" in incomplete_verdict["analysis_verdict"]["unresolved"]
        contract_validator("verdict-output", incomplete_verdict)


# ---------------------------------------------------------------------------
# (5) Fixture: PQ cited but only PROVEN-INITIAL -> complete: false
# ---------------------------------------------------------------------------


class TestProvenInitialOnly:
    """When a PQ's cited fact is only PROVEN-INITIAL (not PROVEN-FULL),
    verdict must have complete=false (mirrors C0a)."""

    @pytest.fixture
    def initial_only_verdict(self) -> dict:
        return _make_verdict(
            complete=False,
            primary_questions=[
                _pq("q1", False, "F010", "PROVEN-INITIAL",
                    "confidence_band is PROVEN-INITIAL, not PROVEN-FULL"),
            ],
            unresolved=["q1"],
        )

    def test_complete_false(self, contract_validator, initial_only_verdict) -> None:
        assert initial_only_verdict["analysis_verdict"]["complete"] is False
        contract_validator("verdict-output", initial_only_verdict)

    def test_q_in_unresolved(self, contract_validator, initial_only_verdict) -> None:
        assert "q1" in initial_only_verdict["analysis_verdict"]["unresolved"]
        contract_validator("verdict-output", initial_only_verdict)


# ---------------------------------------------------------------------------
# (6) Fixture: same-topic 2 PROVEN facts without supersedes -> contradictions
# ---------------------------------------------------------------------------


class TestContradictionDetection:
    """When two PROVEN facts answer the same topic without supersedes/CONFLICT,
    verdict must have contradictions non-empty and correct=false."""

    @pytest.fixture
    def contradiction_verdict(self) -> dict:
        return _make_verdict(
            complete=True,
            correct=False,
            primary_questions=[
                _pq("q1", True, "F010", "PROVEN-FULL", None),
            ],
            unresolved=[],
            contradictions=[
                {
                    "question": "q1",
                    "fact_a": "F010",
                    "fact_b": "F015",
                    "nature": "same topic, no supersedes or CONFLICT resolution",
                }
            ],
        )

    def test_correct_false(self, contract_validator, contradiction_verdict) -> None:
        assert contradiction_verdict["analysis_verdict"]["correct"] is False
        contract_validator("verdict-output", contradiction_verdict)

    def test_contradictions_nonempty(
        self, contract_validator, contradiction_verdict
    ) -> None:
        assert len(contradiction_verdict["analysis_verdict"]["contradictions"]) > 0
        contract_validator("verdict-output", contradiction_verdict)

    def test_contradiction_fields(
        self, contract_validator, contradiction_verdict
    ) -> None:
        c = contradiction_verdict["analysis_verdict"]["contradictions"][0]
        assert c["question"] == "q1"
        assert c["fact_a"] == "F010"
        assert c["fact_b"] == "F015"
        assert "nature" in c
        contract_validator("verdict-output", contradiction_verdict)


# ---------------------------------------------------------------------------
# (7) Fixture: model_selection PQ with 1 PROVEN + rest REFUTED -> complete: true
# ---------------------------------------------------------------------------


class TestModelSelectionC0b:
    """When a model_selection PQ has at least 1 PROVEN fact and the rest REFUTED,
    verdict must have complete=true (mirrors C0b)."""

    @pytest.fixture
    def c0b_verdict(self) -> dict:
        return _make_verdict(
            complete=True,
            primary_questions=[
                _pq("q_model", True, "F030", "PROVEN-FULL", None),
            ],
            unresolved=[],
        )

    def test_complete_true(self, contract_validator, c0b_verdict) -> None:
        assert c0b_verdict["analysis_verdict"]["complete"] is True
        contract_validator("verdict-output", c0b_verdict)


# ---------------------------------------------------------------------------
# (8) Structural: required fields missing -> rejection
# ---------------------------------------------------------------------------


class TestRequiredFields:
    """Missing required fields must cause schema validation failure."""

    def test_missing_meta_rejected(self, contract_validator) -> None:
        payload = copy.deepcopy(_BASE_VERDICT)
        del payload["_meta"]
        with pytest.raises(AssertionError, match="schema.*violations"):
            contract_validator("verdict-output", payload)

    def test_missing_analysis_verdict_rejected(self, contract_validator) -> None:
        payload = copy.deepcopy(_BASE_VERDICT)
        del payload["analysis_verdict"]
        with pytest.raises(AssertionError, match="schema.*violations"):
            contract_validator("verdict-output", payload)

    def test_missing_self_audit_rejected(self, contract_validator) -> None:
        payload = copy.deepcopy(_BASE_VERDICT)
        del payload["self_audit"]
        with pytest.raises(AssertionError, match="schema.*violations"):
            contract_validator("verdict-output", payload)

    def test_missing_complete_in_analysis_verdict(self, contract_validator) -> None:
        payload = copy.deepcopy(_BASE_VERDICT)
        del payload["analysis_verdict"]["complete"]
        with pytest.raises(AssertionError, match="schema.*violations"):
            contract_validator("verdict-output", payload)


# ---------------------------------------------------------------------------
# (9) Self-audit enum enforcement
# ---------------------------------------------------------------------------


class TestSelfAuditEnum:
    """evidence_strength must be one of: strong, mixed, weak."""

    @pytest.mark.parametrize("strength", ["strong", "mixed", "weak"])
    def test_valid_evidence_strength(
        self, contract_validator, strength: str
    ) -> None:
        payload = copy.deepcopy(_BASE_VERDICT)
        payload["self_audit"]["evidence_strength"] = strength
        contract_validator("verdict-output", payload)

    def test_invalid_evidence_strength_rejected(self, contract_validator) -> None:
        payload = copy.deepcopy(_BASE_VERDICT)
        payload["self_audit"]["evidence_strength"] = "excellent"
        with pytest.raises(AssertionError, match="schema.*violations"):
            contract_validator("verdict-output", payload)


# ---------------------------------------------------------------------------
# (10) Sample SHA256 format
# ---------------------------------------------------------------------------


class TestSampleSha256:
    """sample_sha256 must be a 64-char lowercase hex string."""

    def test_valid_sha256(self, contract_validator) -> None:
        payload = copy.deepcopy(_BASE_VERDICT)
        payload["sample_sha256"] = "a" * 64
        contract_validator("verdict-output", payload)

    def test_invalid_sha256_too_short(self, contract_validator) -> None:
        payload = copy.deepcopy(_BASE_VERDICT)
        payload["sample_sha256"] = "abc123"
        with pytest.raises(AssertionError, match="schema.*violations"):
            contract_validator("verdict-output", payload)
