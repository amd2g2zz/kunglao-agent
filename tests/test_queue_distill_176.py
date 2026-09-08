# -*- coding: utf-8 -*-
"""Shape contracts for the unidbg harness-bringup and algo-recovery cards
and the five amended cards they neighbor (unidbg-env-filling,
falsifier-library, jsvmp-triage, web-risk-control, web-crawler-engineering).

Shape-level assertions only: frontmatter (name + description with a
when-not boundary), the 200-line budget, balanced code fences, the
attribution format (evidence count + variant inspiration + pinned
methodology family rows), landed-delta content assertions per card, and
the ZERO-LITERAL corpus-identifier guard (pre-computed token digests
only — this file carries no identifying literal).
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
RELIB = ROOT / "references" / "re-library"

BRINGUP_CARD = RELIB / "unidbg-harness-bringup.md"
ALGO_CARD = RELIB / "unidbg-algo-recovery.md"
NEW_CARDS = [BRINGUP_CARD, ALGO_CARD]

UNIDBG_CARD = RELIB / "unidbg-env-filling.md"
FALSIFIER_CARD = RELIB / "falsifier-library.md"
JSVMP_CARD = RELIB / "jsvmp-triage.md"
WEB_RISK_CARD = RELIB / "web-risk-control.md"
WEB_CRAWL_CARD = RELIB / "web-crawler-engineering.md"
CHANGED_CARDS = [UNIDBG_CARD, FALSIFIER_CARD, JSVMP_CARD, WEB_RISK_CARD, WEB_CRAWL_CARD]

ALL_TOUCHED = NEW_CARDS + CHANGED_CARDS

# Cards that must NOT grow (at budget, or over budget).
NATIVE_SIGN_CARD = RELIB / "native-sign-recovery.md"
ANTI_ANALYSIS_CARD = RELIB / "anti-analysis.md"

# Source-identifying tokens matched by PRE-COMPUTED sha256 digests (the
# ZERO-LITERAL standard: only pre-computed digests appear in this file).
# Digests are of lowercased tokens as produced by the tokenizer below,
# computed out of band:
#   hashlib.sha256(token.encode()).hexdigest()
# Coverage: distinctive source-repo name fragments and a romanized
# article-title token. Tokens that tokenize into generic vocabulary
# (vendor names, single common words) are intentionally absent — a
# false-positive-prone denylist guards less than a targeted one.
FORBIDDEN_TOKEN_HASHES = {
    "1889c7e0e5b4be9b8f2a2f4386c3e62d793c217897c10f97abe04e634da88841",
    "269b49b563282d581f793525602cbc4f3e7e1a3ed4a8dd4e6f609773cd6593a2",
    "2fada8ed5bf09c4177d2190366d04f3c193823389378b90e92f680053b641537",
    "7af2465c9fb905c63a1f39f82250d66719a47983bdecb3383c1040e5f2379f41",
    "b75b6b729495c718198820330a6fc5456ac712c507eb32f146b83e070c022ab5",
    "fb3109f50dd74898c7a0fd0343e7b1fb1e8b20971a8153129310a43f5da34414",
}


def _token_hashes(text: str) -> set[str]:
    """sha256 of every alphanumeric token in the lowercased text."""
    return {
        hashlib.sha256(tok.encode()).hexdigest()
        for tok in re.findall(r"[A-Za-z0-9_]+", text.lower())
    }


_CATALOG_ROW = re.compile(r"^\|(?!\s*[-|]).+\|", re.MULTILINE)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _frontmatter(path: Path) -> str:
    text = _text(path)
    assert text.startswith("---\n"), f"{path.name}: missing frontmatter"
    return text.split("---\n", 2)[1]


def _body_lines(path: Path) -> int:
    """Budget unit: lines after the frontmatter block. The frontmatter is
    the machine-consumed metadata home and does not count as knowledge bulk."""
    text = _text(path)
    if text.startswith("---\n"):
        return len(text.split("---\n", 2)[2].splitlines())
    return len(text.splitlines())


def _family_rows(card: Path) -> list[str]:
    return [ln for ln in _text(card).splitlines()
            if re.match(r"^\| \*\*\d+\.", ln)]


# ---------- (a) new-card frontmatter ----------

@pytest.mark.parametrize("card", NEW_CARDS)
def test_new_card_frontmatter_name_and_description(card: Path):
    fm = _frontmatter(card)
    assert re.search(r"^name:\s*\S", fm, re.MULTILINE), f"{card.name}: no name"
    assert re.search(r"^description:\s*\S", fm, re.MULTILINE), f"{card.name}: no desc"


@pytest.mark.parametrize("card", NEW_CARDS)
def test_new_card_frontmatter_is_valid_yaml(card: Path):
    fm = yaml.safe_load(_frontmatter(card))
    assert isinstance(fm, dict), f"{card.name}: frontmatter must parse to a mapping"
    assert fm.get("name") == card.stem, f"{card.name}: name must match the stem"
    assert isinstance(fm.get("description"), str) and fm["description"]


@pytest.mark.parametrize("card", NEW_CARDS)
def test_new_card_description_carries_when_not_boundary(card: Path):
    fm = _frontmatter(card)
    desc = re.search(r"^description:\s*(.+?)(?=^\w+:|\Z)", fm, re.MULTILINE | re.DOTALL).group(1)
    assert re.search(r"[Nn]ot (for|when|use)|Skip (this|when)|do not use", desc), (
        f"{card.name}: description lacks a when-not boundary"
    )


# ---------- (b) budgets ----------

@pytest.mark.parametrize("card", NEW_CARDS)
def test_new_cards_within_200_line_budget(card: Path):
    n = _body_lines(card)
    assert n <= 200, f"{card.name}: {n} body lines exceeds the 200-line budget"


def test_unidbg_env_card_stays_within_budget():
    """unidbg-env-filling absorbs its deltas only within its budget."""
    n = _body_lines(UNIDBG_CARD)
    assert n <= 200, f"unidbg-env-filling grew to {n} body lines (budget 200)"


def test_web_cards_stay_within_budget():
    for card in (WEB_RISK_CARD, WEB_CRAWL_CARD, JSVMP_CARD, FALSIFIER_CARD):
        n = _body_lines(card)
        assert n <= 200, f"{card.name}: {n} body lines exceeds the 200-line budget"


def test_no_growth_cards_untouched():
    """native-sign-recovery sits at its budget and must not grow;
    anti-analysis is over budget and outside this file's scope."""
    assert _body_lines(NATIVE_SIGN_CARD) <= 200
    assert _body_lines(ANTI_ANALYSIS_CARD) <= 800  # current size, must not grow


# ---------- (c) fences ----------

@pytest.mark.parametrize("card", ALL_TOUCHED)
def test_code_fences_balanced(card: Path):
    n = _text(card).count("```")
    assert n % 2 == 0, f"{card.name}: unbalanced code fences ({n})"


# ---------- (d) attribution format ----------

@pytest.mark.parametrize("card", NEW_CARDS)
def test_new_card_tables_carry_evidence_and_variant_columns(card: Path):
    text = _text(card)
    assert "Evidence" in text, f"{card.name}: catalog rows missing Evidence count"
    assert "Variant inspiration" in text, f"{card.name}: rows missing Variant inspiration"


@pytest.mark.parametrize(("card", "minimum"), [
    (BRINGUP_CARD, 2),
    (ALGO_CARD, 3),
])
def test_new_card_sections_pin_methodology_family(card: Path, minimum: int):
    n = len(re.findall(r"^\*\*Family:", _text(card), re.MULTILINE))
    assert n >= minimum, f"{card.name}: only {n} family attributions (need >= {minimum})"


@pytest.mark.parametrize(("card", "minimum"), [
    (BRINGUP_CARD, 6),
    (ALGO_CARD, 8),
])
def test_new_card_catalog_rows_have_minimum_hit_information(card: Path, minimum: int):
    rows = [ln for ln in _text(card).splitlines() if _CATALOG_ROW.match(ln)]
    assert len(rows) >= minimum, f"{card.name}: only {len(rows)} catalog rows (need >= {minimum})"


# ---------- (e) unidbg deltas: env card + adjacent bring-up card ----------

def test_unidbg_card_lands_env_deltas():
    text = _text(UNIDBG_CARD)
    assert "vDSO" in text, "vDSO trap delta missing from the syscall section"
    assert re.search(r"three (supply )?classes|3-class", text, re.IGNORECASE), (
        "syscall supply-class taxonomy delta missing"
    )
    assert "pre-resolut" in text, "class-hierarchy pre-resolution trap missing"
    assert "record" in text.lower() and "replay" in text.lower(), (
        "record-replay fallback missing"
    )


def test_bringup_card_lands_setup_deltas():
    text = _text(BRINGUP_CARD)
    assert "xHook" in text, "xHook delta missing"
    assert re.search(r"refresh", text, re.IGNORECASE), "xHook refresh-missing signature missing"
    assert re.search(r"never stack|stacking two|two frameworks|never.*two", text, re.IGNORECASE), (
        "never-stack-two-frameworks rule missing"
    )
    assert re.search(r"timing", text, re.IGNORECASE), "hook timing matrix missing"
    assert "CodeHook" in text, "CodeHook/backend incompatibility missing"
    assert "dump" in text.lower(), "packed-SO dump-then-load missing"
    assert re.search(r"thread.{0,12}dispatch", text, re.IGNORECASE), "thread-dispatcher hang missing"


def test_bringup_card_states_split_rationale():
    text = _text(BRINGUP_CARD)
    assert "unidbg-env-filling" in text, "must point at the aggregation target it split from"
    assert "native-sign-recovery" in text, "must point at the loop this card feeds"


# ---------- (f) recovery deltas card ----------

def test_algo_card_lands_recovery_deltas():
    text = _text(ALGO_CARD)
    for token in ("128", "RSA", "movz", "movk", "endianness",
                  "provenance", "BN_mod_exp_mont", "verifier"):
        assert token in text, f"recovery delta missing: {token}"


def test_algo_card_lands_stack_reading_error_class_mapping():
    text = _text(ALGO_CARD)
    assert re.search(r"stack", text, re.IGNORECASE), "stack-reading delta missing"
    assert re.search(r"error.class|failure class", text, re.IGNORECASE), (
        "error-class mapping delta missing"
    )


def test_algo_card_points_at_the_ladder_it_complements():
    text = _text(ALGO_CARD)
    assert "native-sign-recovery" in text, "must point at the boundary-first ladder"
    assert "falsifier-library" in text, "must point at the falsifier families it mirrors"


def test_ladder_card_not_duplicated():
    """native-sign-recovery owns the six-step ladder; the delta card must
    reference it, not restate ordered steps."""
    text = _text(ALGO_CARD)
    assert "Step 1" not in text and "Step 6" not in text, (
        "delta card must not restate the ladder's ordered steps"
    )


# ---------- (g) falsifier family 19 ----------

def test_falsifier_has_family_19_row():
    rows = _family_rows(FALSIFIER_CARD)
    f19 = [r for r in rows if r.startswith("| **19.")]
    assert len(f19) == 1, "family 19 row missing (or duplicated)"


def test_family19_row_schema_matches_house_shape():
    row = [r for r in _family_rows(FALSIFIER_CARD) if r.startswith("| **19.")][0]
    assert row.endswith("|"), "row must be one complete table line"
    assert re.match(r"^\| \*\*19\. [^*]+\*\* \([^)]+\) \|", row), (
        "row schema must match the house family shape: bold numbered title, "
        "attestation parenthetical, single experiments cell"
    )


def test_family19_row_two_sided_outcomes_and_score_model():
    row = [r for r in _family_rows(FALSIFIER_CARD) if r.startswith("| **19.")][0]
    assert "→ ✓" in row and "✗" in row, "row must carry trigger → ✓ / ✗ notation"
    assert "FAKE_RESULT" in row, "FAKE_RESULT-not-abort score model missing"
    for token in ("pending-exception", "uname", "time", "FPSR"):
        assert token in row, f"detection face token missing: {token}"
    assert "score" in row.lower(), "additive score semantics must be named"


def test_family19_row_lists_six_faces():
    row = [r for r in _family_rows(FALSIFIER_CARD) if r.startswith("| **19.")][0]
    faces = re.findall(r"\(([a-e])\)|\(f\)", row)
    letters = set(re.findall(r"\(([a-f])\)", row))
    assert {"a", "b", "c", "d", "e", "f"} <= letters, (
        f"six-face inventory incomplete: found {sorted(letters)}"
    )


def test_family19_no_hard_always_rule():
    row = [r for r in _family_rows(FALSIFIER_CARD) if r.startswith("| **19.")][0]
    assert "always" not in row.lower(), "no hard always-rules in falsifier rows"


# ---------- (h) sensor-VM anatomy in jsvmp-triage ----------

def test_jsvmp_card_lands_sensor_vm_anatomy():
    text = _text(JSVMP_CARD)
    assert re.search(r"property.resolution", text, re.IGNORECASE), (
        "property-resolution memory model missing"
    )
    assert re.search(r"nonexistent.{0,12}opcode|opcode.{0,20}no handler|unmapped opcode",
                     text, re.IGNORECASE), "exit-via-nonexistent-opcode missing"
    assert "lifter" in text.lower(), "trace->opcode->lifter face missing"
    assert "CFG" in text, "lifter->CFG face missing"


def test_jsvmp_card_carries_pointer_level_disclaimer():
    """[14] scope guard: the sensor FORMAT is pointer-level knowledge only —
    the card must say so instead of overclaiming a field map."""
    text = _text(JSVMP_CARD)
    assert re.search(r"pointer.level|field.map|field layout|verify against a live capture",
                     text, re.IGNORECASE), (
        "pointer-level disclaimer for the sensor format missing"
    )


# ---------- (i) web increments ----------

def test_web_risk_card_lands_cloudflare_deltas():
    text = _text(WEB_RISK_CARD)
    assert "cf_clearance" in text, "cf_clearance delta missing"
    assert re.search(r"exit.IP|出口.{0,4}IP", text), "exit-IP binding missing"
    assert re.search(r"vision|视觉", text, re.IGNORECASE), "vision locator rung missing"
    assert re.search(r"HTML", text), "HTML locator rung missing"


def test_web_crawler_card_lands_captcha_deltas():
    text = _text(WEB_CRAWL_CARD)
    assert re.search(r"canny", text, re.IGNORECASE), "canny-edge-first matching missing"
    assert "SceneId" in text, "aliyun SceneId triad missing"
    assert re.search(r"prefix|前缀", text, re.IGNORECASE), "endpoint prefix triad missing"
    assert re.search(r"confus|混淆|误判", text, re.IGNORECASE), "vendor confusion taxonomy missing"


# ---------- (j) ZERO-LITERAL corpus guard ----------

@pytest.mark.parametrize("card", ALL_TOUCHED)
def test_zero_corpus_identifiers(card: Path):
    leaked = FORBIDDEN_TOKEN_HASHES & _token_hashes(_text(card))
    assert not leaked, f"{card.name}: corpus-identifying token leak (digests: {sorted(leaked)})"


# ---------- (k) no tracker numbers in card bodies (relib audit rule) ----------

@pytest.mark.parametrize("card", NEW_CARDS)
def test_new_cards_carry_no_tracker_numbers(card: Path):
    body = _text(card).split("---", 2)[2]
    hits = re.findall(r"#\d{3}\b", body)
    assert not hits, f"{card.name}: tracker-number residue {hits} (curation is human)"
