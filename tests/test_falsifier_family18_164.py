# -*- coding: utf-8 -*-
"""tests/test_falsifier_family18_164.py — #164 debuggability enablement ladder.

Thin-increment contract (#164): ONE new family row in the falsifier-library
card — family 18, the setup-side enablement family (debugger attach refused
/ JDWP thread absent), orthogonal to the landed detection-side families
(11/15/17 cover checks that fire AFTER attach; 18 covers refusal BEFORE it).
Row must be schema-identical to the families 15/17 rows (bold numbered title,
attestation-marker parenthetical, trigger → ✓/✗ two-sided semantics) and
row-sized: no new card, no new sections, card total within the re-library
line budget. Rule-10 stale-tool compat notes (android_server →
android_server64; DDMS removed from the modern SDK) ride as compact
parentheticals inside the row, never as a new section. Zero corpus
identifiers: the card cites repo-relative cards only — no http(s) links.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT / "references" / "re-library" / "falsifier-library.md"
INDEX = ROOT / "references" / "_INDEX.md"

CARD_LINE_BUDGET = 200  # re-library card budget (vm-protection-anatomy precedent)


def _text() -> str:
    return CARD.read_text(encoding="utf-8")


def _rows() -> list[str]:
    return [ln for ln in _text().splitlines()
            if re.match(r"^\| \*\*\d+\.", ln)]


def _family18() -> str:
    rows = [r for r in _rows() if r.startswith("| **18.")]
    assert len(rows) == 1, "family 18 row missing (or duplicated)"
    return rows[0]


# ---------- existence / line budget ----------


def test_card_within_line_budget() -> None:
    lines = len(_text().splitlines())
    assert lines <= CARD_LINE_BUDGET, (
        f"falsifier-library has {lines} lines, budget {CARD_LINE_BUDGET}")


def test_family_count_is_18() -> None:
    # 2026-09-08 (#176): family 19 (emulator-detection faces + FAKE_RESULT
    # score model) joins the table per that wave's falsifier deliverable;
    # the count assert moves with reality — family 18's own schema tests
    # below are unchanged.
    assert len(_rows()) == 19, f"expected 19 family rows, found {len(_rows())}"


# ---------- row schema (identical to families 15/17) ----------


def test_row_is_single_table_line_with_marker_parenthetical() -> None:
    row = _family18()
    assert row.endswith("|"), "row must be one complete table line"
    assert re.match(r"^\| \*\*18\. [^*]+\*\* \([^)]+\) \| .+ \|$", row), (
        "row schema must match families 15/17: bold numbered title, "
        "attestation-marker parenthetical, single experiments cell")


def test_row_trigger_two_sided_outcome_semantics() -> None:
    row = _family18()
    assert "→ ✓" in row and "✗" in row, (
        "row must carry the table's trigger → ✓ / ✗ notation")
    assert "falsifier" in row.lower(), (
        "the re-verify closure must be named as the fix's own falsifier")


# ---------- hit information contract (scenario + how + expected) ----------


def test_row_failure_signature_and_decision_order() -> None:
    row = _family18()
    for token in ("attach", "JDWP", "ro.debuggable", "android:debuggable",
                  "getprop"):
        assert token in row, f"signature/decision-order token missing: {token}"
    assert "repackage" in row and "resign" in row, "per-APK rung missing"
    assert "AVD" in row, "emulator-default note missing"


def test_row_heuristic_voice_not_a_hard_rule() -> None:
    row = _family18()
    assert "always" not in row.lower(), "no hard always-rules in falsifier rows"
    assert "when" in row.lower(), "row must keep the when-X-do-Y scaffold"


def test_row_names_alternate_signature_on_negative() -> None:
    row = _family18()
    assert "families 11/15" in row, (
        "negative closure must cross-reference the detection-side families")


# ---------- rule-10 stale-tool compat notes (compact parentheticals) ----------


def test_rule10_notes_present_in_row_not_a_section() -> None:
    row = _family18()
    assert "android_server64" in row, "modern IDA agent naming missing"
    assert "android_server" in row.replace("android_server64", ""), (
        "legacy 32-bit naming must be named, not silently replaced")
    assert "DDMS" in row, "DDMS staleness note missing"
    for ln in _text().splitlines():
        assert not re.match(r"^#+ .*(android_server|DDMS)", ln), (
            "compat notes must stay parentheticals, not a new section")


# ---------- index consistency + zero corpus identifiers ----------


def test_index_desc_tracks_family_count() -> None:
    idx = INDEX.read_text(encoding="utf-8")
    m = re.search(
        r"re-library/falsifier-library\.md` \| [^|]+ \| "
        r"Hypothesis-family falsifier pattern library: (\d+) families",
        idx)
    assert m, "falsifier-library index row not found in references/_INDEX.md"
    assert int(m.group(1)) == len(_rows()), (
        "references/_INDEX.md desc family count is stale vs the card")


def test_card_carries_no_external_corpus_identifiers() -> None:
    text = _text()
    assert "http://" not in text and "https://" not in text, (
        "zero corpus identifiers: the card cites repo-relative cards only")


# ---------- frontmatter must be valid YAML (#164 addendum defect) ----------


def test_frontmatter_is_valid_yaml() -> None:
    """Regression guard: an unquoted ': ' inside the description plain
    scalar ('...kill experiments: the trigger...') made yaml.safe_load
    fail with 'mapping values are not allowed here' — the defect class is
    frontmatter-that-must-parse, so parse it here."""
    parts = _text().split("---", 2)
    assert len(parts) >= 3, "card frontmatter block missing"
    fm = yaml.safe_load(parts[1])
    assert isinstance(fm, dict), "frontmatter must parse to a mapping"
    assert fm.get("name") == "falsifier-library"
    assert isinstance(fm.get("description"), str) and fm["description"]
