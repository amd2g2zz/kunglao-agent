# -*- coding: utf-8 -*-
"""#165 course-distillation card contracts (unidbg env-filling + signature-check bypass).

RED-first contract tests for the two new re-library cards distilled from the
26-lesson course corpus (#165). Shape-level assertions only:

  (a) frontmatter: name + description present; description carries a
      when-not boundary (the #165 noise bar: every desc lets the agent
      reject a non-applicable item before opening it);
  (b) budget: each card <= 200 lines;
  (c) fences: fenced code blocks balanced;
  (d) attribution format (issue deliverable 3): the catalog tables carry
      Evidence and Variant inspiration columns and every catalog section
      pins its methodology family;
  (e) deployment preconditions (issue deliverable 2, binding): the unidbg
      card states JDK + Maven toolchain deployment and that unidbg plus its
      dependency tree are pulled from remote (clone + first-build
      dependency resolution);
  (f) corpus-identifier grep-zero: no corpus names/titles/URLs/handles in
      any landed artifact (issue privacy rule);
  (g) dedup pointers: each card cross-references the existing card that
      owns the shared loop (native-sign-recovery) instead of duplicating it.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RELIB = ROOT / "references" / "re-library"

UNIDBG_CARD = RELIB / "unidbg-env-filling.md"
SIGNATURE_CARD = RELIB / "signature-check-bypass.md"

NEW_CARDS = [UNIDBG_CARD, SIGNATURE_CARD]

# Corpus identifiers: repo name, course title fragments, author handles,
# forum hosts, demo-package/demo-lib names seen in the corpus. These and
# the corpus article URLs must never appear in any landed artifact.
FORBIDDEN = [
    "ZJ595",
    "AndroidReverse",
    "wuaipojie",
    "52pojie",
    "kanxue",
    "pediy",
    "TigerTally",
    "libszstone",
    "linkejin",
    "thread-17",
    "thread-18",
]

_CATALOG_ROW = re.compile(r"^\|(?!\s*[-|]).+\|", re.MULTILINE)


# ---------- fixtures ----------

@pytest.fixture(scope="module")
def card_text() -> dict[str, str]:
    out = {}
    for card in NEW_CARDS:
        assert card.is_file(), f"card missing: {card}"
        out[card.name] = card.read_text(encoding="utf-8")
    return out


# ---------- (a) frontmatter ----------

def test_frontmatter_has_name_and_description():
    for card in NEW_CARDS:
        text = card.read_text(encoding="utf-8")
        assert text.startswith("---\n"), f"{card.name}: missing frontmatter"
        fm = text.split("---\n", 2)[1]
        assert re.search(r"^name:\s*\S", fm, re.MULTILINE), f"{card.name}: no name"
        assert re.search(r"^description:\s*\S", fm, re.MULTILINE), f"{card.name}: no description"


def test_description_carries_when_not_boundary():
    """#165 noise bar: the desc must let the agent reject non-applicable items."""
    for card in NEW_CARDS:
        text = card.read_text(encoding="utf-8")
        fm = text.split("---\n", 2)[1]
        desc = re.search(r"^description:\s*(.+?)(?=^\w+:|\Z)", fm, re.MULTILINE | re.DOTALL).group(1)
        assert re.search(r"[Nn]ot (for|when|use)|Skip (this|when)|do not use", desc), (
            f"{card.name}: description lacks a when-not boundary"
        )


# ---------- (b) budget ----------

def test_cards_within_200_line_budget():
    for card in NEW_CARDS:
        n = len(card.read_text(encoding="utf-8").splitlines())
        assert n <= 200, f"{card.name}: {n} lines exceeds the 200-line budget"


# ---------- (c) fences ----------

def test_code_fences_balanced():
    for card in NEW_CARDS:
        text = card.read_text(encoding="utf-8")
        n = text.count("```")
        assert n % 2 == 0, f"{card.name}: unbalanced code fences ({n})"


# ---------- (d) attribution format ----------

def test_catalog_tables_carry_evidence_and_variant_columns():
    for card in NEW_CARDS:
        text = card.read_text(encoding="utf-8")
        assert "Evidence" in text, f"{card.name}: catalog rows missing Evidence count"
        assert "Variant inspiration" in text, (
            f"{card.name}: catalog rows missing Variant inspiration field"
        )


def test_every_catalog_section_pins_methodology_family(card_text):
    """Attribution deliverable 3: each catalog section names its house family."""
    expectations = {
        UNIDBG_CARD.name: 4,   # log-decode / stubbing-loop / env-integrity / interposition sections
        SIGNATURE_CARD.name: 2,  # acquisition-channel / countermeasure-ladder sections
    }
    for name, minimum in expectations.items():
        text = card_text[name]
        n = len(re.findall(r"^\*\*Family:", text, re.MULTILINE))
        assert n >= minimum, f"{name}: only {n} family attributions (need >= {minimum})"


def test_catalog_rows_have_minimum_hit_information(card_text):
    """Hit-info contract: scenario + how + expected. Table rows must be dense
    enough to carry all three (>= 8 catalog body rows in the unidbg card,
    >= 5 in the signature card)."""
    expectations = {UNIDBG_CARD.name: 8, SIGNATURE_CARD.name: 5}
    for name, minimum in expectations.items():
        text = card_text[name]
        rows = [ln for ln in text.splitlines() if _CATALOG_ROW.match(ln)]
        assert len(rows) >= minimum, f"{name}: only {len(rows)} catalog rows (need >= {minimum})"


# ---------- (e) deployment preconditions (binding deliverable 2) ----------

def test_unidbg_card_states_deployment_preconditions():
    text = UNIDBG_CARD.read_text(encoding="utf-8")
    assert "JDK" in text, "deployment block must state the JDK requirement"
    assert "Maven" in text, "deployment block must state the Maven toolchain"
    assert re.search(r"git clone|cloned from|pulled from", text, re.IGNORECASE), (
        "deployment block must state unidbg is pulled from remote (clone)"
    )
    assert re.search(r"first build|first-build", text, re.IGNORECASE), (
        "deployment block must state first-build dependency resolution"
    )


def test_native_sign_recovery_card_untouched_by_pointer_only():
    """native-sign-recovery.md is at its 200-line budget — the deployment
    block lands in the new card and the existing card stays byte-identical
    is enforced by review; here we only assert the new card POINTS at the
    stubbing loop instead of duplicating it (dedup deliverable)."""
    text = UNIDBG_CARD.read_text(encoding="utf-8")
    assert "native-sign-recovery" in text, "unidbg card must point at the stubbing-loop card"


# ---------- (f) corpus-identifier grep-zero ----------

@pytest.mark.parametrize("artifact", [
    UNIDBG_CARD,
    SIGNATURE_CARD,
    ROOT / "templates" / "frida" / "rpc-skeleton.js.tmpl",
    ROOT / "templates" / "unidbg" / "harness.java.tmpl",
    ROOT / "scripts" / "install_unidbg.sh",
    ROOT / "scripts" / "install_unidbg.py",
])
def test_zero_corpus_identifiers(artifact: Path):
    assert artifact.is_file(), f"artifact missing: {artifact}"
    text = artifact.read_text(encoding="utf-8")
    for token in FORBIDDEN:
        assert token.lower() not in text.lower(), f"{artifact.name}: corpus identifier leak: {token}"


# ---------- (g) signature card dedup pointers ----------

def test_signature_card_points_at_owned_families():
    text = SIGNATURE_CARD.read_text(encoding="utf-8")
    assert "stacked-protections" in text, "pinning overlaps route to stacked-protections"
    assert "anti-analysis" in text, "instrumentation-detection overlaps route to anti-analysis"
