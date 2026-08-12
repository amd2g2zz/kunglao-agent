"""tests/test_evals_schema.py — structural validation of evals/evals.json.

Guards the skill-creator contract: evals/evals.json must exist, be valid JSON,
and contain >= 3 evals each with required fields (id, prompt, expected_output,
expectations). Issue #117.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EVALS_PATH = ROOT / "evals" / "evals.json"

REQUIRED_EVAL_KEYS = {"id", "prompt", "expected_output", "expectations"}
OPTIONAL_EVAL_KEYS = {"files"}
VALID_CLASSIFICATIONS = {"clean", "benign", "suspicious", "malicious"}


class TestEvalsJsonExists:
    """evals/evals.json exists and is valid JSON."""

    def test_file_exists(self):
        assert EVALS_PATH.exists(), (
            f"evals/evals.json must exist (skill-creator contract)"
        )

    def test_valid_json(self):
        data = json.loads(EVALS_PATH.read_text(encoding="utf-8"))
        assert isinstance(data, dict)


class TestEvalsJsonStructure:
    """Top-level structure: skill_name + evals array."""

    @pytest.fixture()
    def evals_data(self):
        return json.loads(EVALS_PATH.read_text(encoding="utf-8"))

    def test_skill_name(self, evals_data):
        assert evals_data.get("skill_name") == "kunglao-agent", (
            "skill_name must be 'kunglao-agent'"
        )

    def test_evals_is_array(self, evals_data):
        assert isinstance(evals_data.get("evals"), list), (
            "'evals' must be an array"
        )

    def test_minimum_three_evals(self, evals_data):
        assert len(evals_data["evals"]) >= 3, (
            f"Must have >= 3 evals, found {len(evals_data['evals'])}"
        )


class TestEvalsJsonFields:
    """Each eval entry has required fields with correct types."""

    @pytest.fixture()
    def evals(self):
        data = json.loads(EVALS_PATH.read_text(encoding="utf-8"))
        return data["evals"]

    def test_required_keys_present(self, evals):
        for i, entry in enumerate(evals):
            missing = REQUIRED_EVAL_KEYS - set(entry.keys())
            assert not missing, (
                f"eval[{i}] (id={entry.get('id')}) missing keys: {missing}"
            )

    def test_id_is_positive_int(self, evals):
        for i, entry in enumerate(evals):
            assert isinstance(entry["id"], int) and entry["id"] > 0, (
                f"eval[{i}].id must be a positive integer, got {entry['id']!r}"
            )

    def test_prompt_is_string(self, evals):
        for i, entry in enumerate(evals):
            assert isinstance(entry["prompt"], str) and len(entry["prompt"]) > 0, (
                f"eval[{i}].prompt must be a non-empty string"
            )

    def test_expected_output_is_string(self, evals):
        for i, entry in enumerate(evals):
            assert isinstance(entry["expected_output"], str) and len(entry["expected_output"]) > 0, (
                f"eval[{i}].expected_output must be a non-empty string"
            )

    def test_expectations_is_nonempty_list(self, evals):
        for i, entry in enumerate(evals):
            assert isinstance(entry["expectations"], list) and len(entry["expectations"]) >= 1, (
                f"eval[{i}].expectations must be a list with >= 1 entries"
            )
            for j, exp in enumerate(entry["expectations"]):
                assert isinstance(exp, str) and len(exp) > 0, (
                    f"eval[{i}].expectations[{j}] must be a non-empty string"
                )

    def test_files_optional_but_list(self, evals):
        for i, entry in enumerate(evals):
            if "files" in entry:
                assert isinstance(entry["files"], list), (
                    f"eval[{i}].files must be a list when present"
                )

    def test_unique_ids(self, evals):
        ids = [e["id"] for e in evals]
        assert len(ids) == len(set(ids)), (
            f"eval ids must be unique, got {ids}"
        )


class TestEvalsCoverageScenarios:
    """The three evals cover the required behavioral scenarios."""

    @pytest.fixture()
    def evals(self):
        data = json.loads(EVALS_PATH.read_text(encoding="utf-8"))
        return {e["id"]: e for e in data["evals"]}

    def test_eval1_convergence_dispatch(self, evals):
        assert 1 in evals, "eval id=1 (convergence dispatch) must exist"
        prompt = evals[1]["prompt"].lower()
        assert any(w in prompt for w in ("convergence", "dispatch", "priority")), (
            "eval 1 prompt should mention convergence/dispatch/priority"
        )
        expectations = " ".join(evals[1]["expectations"]).lower()
        assert "dispatch" in expectations, (
            "eval 1 expectations should mention dispatch behavior"
        )

    def test_eval2_maker_checker(self, evals):
        assert 2 in evals, "eval id=2 (maker-checker) must exist"
        prompt = evals[2]["prompt"].lower()
        assert any(w in prompt for w in ("maker", "checker", "verifier", "blind")), (
            "eval 2 prompt should mention maker-checker / blind verification"
        )
        expectations = " ".join(evals[2]["expectations"]).lower()
        assert "independent" in expectations, (
            "eval 2 expectations should mention independent verification"
        )

    def test_eval3_verdict_decoupled(self, evals):
        assert 3 in evals, "eval id=3 (verdict B4-2) must exist"
        prompt = evals[3]["prompt"].lower()
        assert any(w in prompt for w in ("verdict", "maliciousness", "pq_coverage", "pq-coverage")), (
            "eval 3 prompt should mention verdict/maliciousness/pq_coverage"
        )
        expectations = " ".join(evals[3]["expectations"]).lower()
        assert "maliciousness" in expectations, (
            "eval 3 expectations should mention maliciousness"
        )
        assert "pq_coverage" in expectations or "pq-coverage" in expectations, (
            "eval 3 expectations should mention PQ-coverage"
        )
