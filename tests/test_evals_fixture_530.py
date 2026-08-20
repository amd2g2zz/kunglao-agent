# -*- coding: utf-8 -*-
"""tests/test_evals_fixture_530.py — issue #530 disposition lock:
evals.json #3 migrated from v10 to v11 verdict semantics.

Eval 3 still asserted the v10-era contract (maliciousness 6-dim scoring +
Admiralty+ACH attribution decoupling). Verdict v11 (agents/verdict-scorer.md,
schema_version 2026-08-12-v11) removed both as out-of-scope: the verdict is
PQ-coverage + fact-citation validity only.

These anchors pin the fixture to the live v11 contract.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVALS = ROOT / "evals" / "evals.json"

# v11 schema keys the fixture must exercise (mirrors
# agents/verdict-scorer.md "2026-08-12-v11" output contract).
V11_REQUIRED_TERMS = (
    "analysis_verdict",
    "schema_version",
    "primary_questions",
    "self_audit",
)

# v10-only contract vocabulary that must NOT appear as an expected OUTPUT
# capability (mentioning the ban itself, e.g. "must NOT contain a
# maliciousness section", is the v11-correct framing).
V10_FORBIDDEN_CAPABILITIES = (
    "6-dimension",
    "6-dim",
    "admiralty",
    r"\bach\b",  # word-boundary: bare substring would hit "watch"/"cache"
    "classification field in maliciousness",
    "clean/benign/suspicious/malicious",
)


def _load_third() -> dict:
    data = json.loads(EVALS.read_text(encoding="utf-8"))
    evals = data["evals"]
    assert len(evals) >= 3, "evals.json must have at least 3 entries"
    third = evals[2]
    assert third.get("id") == 3, f"evals[2] must be id=3, got {third.get('id')!r}"
    return third


def test_eval3_prompt_targets_v11_pq_coverage_contract():
    text = json.dumps(_load_third()).lower()
    assert "pq-coverage" in text or "pq_coverage" in text, (
        "eval 3 must target the v11 PQ-coverage verdict contract"
    )
    assert "analysis_verdict" in text, (
        "eval 3 must reference the v11 analysis_verdict schema"
    )


def test_eval3_forbids_v10_capability_vocabulary():
    """The fixture must not EXPECT v10 capabilities (6-dim maliciousness
    scoring, Admiralty/ACH attribution) as verdict output."""
    text = json.dumps(_load_third()).lower()
    for forbidden in V10_FORBIDDEN_CAPABILITIES:
        found = (
            re.search(forbidden, text)
            if forbidden.startswith("\\b")
            else forbidden in text
        )
        assert not found, (
            f"evals.json #3 still expects v10 contract behavior: {forbidden!r}"
        )


def test_eval3_bans_out_of_scope_sections():
    """v11's negative contract: maliciousness/attribution must be named as
    banned output, not expected output."""
    third = _load_third()
    expectations = " ".join(third["expectations"]).lower()
    assert "no 'maliciousness'" in expectations or "not contain" in expectations, (
        "eval 3 expectations must assert the v11 ban on maliciousness/attribution "
        "sections (out-of-scope capabilities)"
    )


def test_eval3_schema_fields_intact():
    """Skill-creator contract keys survive the rewrite
    (tests/test_evals_schema.py enforces the same)."""
    third = _load_third()
    required = {"id", "prompt", "expected_output", "expectations"}
    missing = required - set(third.keys())
    assert not missing, f"evals.json #3 missing keys: {missing}"
