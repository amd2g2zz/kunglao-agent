# -*- coding: utf-8 -*-
"""tests/test_ida_scripting_card_163.py — card contract for the #163 distillation.

The ida-scripting-overlays card (references/re-library/ida-scripting-overlays.md)
lands the #163 correction overlays: legacy-idc -> modern ida_* migration,
headless analysis-wait discipline, Hex-Rays failure-channel edges, and the
rule-10 IDA 9.x version-compat audit rows. This file pins the CARD contract
(house card format + #163 quality bar), not the card's technical claims.

Contract sources:
  - <=200-line card budget (distillation convention)
  - frontmatter name/description shape (house card format)
  - balanced code fences (few-shot listings render)
  - zero corpus identifiers (issue #163 acceptance: no corpus URLs, no
    corpus tool names, no .rst dump references — grep-verified here)
  - synthetic-value markers on worked listings (distillation quality bar)
  - when-not boundary in the desc/body (noise bar: zero false hits)
  - consumer + behavior change named (rule 6 gate)
  - rule-10 audit rows present: old -> break -> modern
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT / "references" / "re-library" / "ida-scripting-overlays.md"

# Corpus-identity ban list (issue #163: "zero corpus identifiers in any
# artifact"). The corpus is an IDA-scripting skill + an MCP bridge project;
# its surface names and material must not leak into the card. IDAPython /
# Hex-Rays PUBLIC API names (ida_auto, idc, ida_hexrays, ...) are universal
# vocabulary, not corpus identifiers, and are allowed.
CORPUS_BANNED = (
    "py_eval",          # upstream bridge tool name (corpus MCP surface)
    ".rst",             # corpus ships full .rst API dumps
    "http://",          # no URLs of any kind
    "https://",
)


def _card_text() -> str:
    assert CARD.exists(), f"card missing: {CARD}"
    return CARD.read_text(encoding="utf-8")


def _frontmatter(text: str) -> dict:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert m, "card must open with a YAML frontmatter block"
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip()
    return fm


def test_frontmatter_shape():
    fm = _frontmatter(_card_text())
    assert fm.get("name") == CARD.stem, "frontmatter name must equal file stem"
    desc = fm.get("description", "")
    assert len(desc) >= 120, "description must be a real routing desc, not a stub"
    assert "when" in desc.lower(), "description must carry a when-to-read trigger"


def test_line_budget_200():
    n = len(_card_text().splitlines())
    assert n <= 200, f"card is {n} lines; budget is 200"


def test_code_fences_balanced():
    text = _card_text()
    fences = [ln for ln in text.splitlines() if ln.strip().startswith("```")]
    assert len(fences) >= 2, "few-shot code listings expected"
    assert len(fences) % 2 == 0, "code fences must open and close in pairs"


def test_zero_corpus_identifiers():
    text = _card_text()
    low = text.lower()
    for token in CORPUS_BANNED:
        assert token not in low, f"corpus identifier leaked into card: {token!r}"


def test_synthetic_value_markers():
    text = _card_text()
    assert re.search(
        r"\bsynthetic\b", text, re.IGNORECASE
    ), "worked listings must declare their values synthetic (quality bar)"


def test_when_not_boundary_present():
    text = _card_text()
    low = text.lower()
    assert (
        "when_not" in low or "not for" in low or "not when" in low
    ), "card must carry a when-not boundary (noise bar: reject non-applicable reads)"


def test_consumer_and_behavior_change_named():
    text = _card_text()
    # rule 6: every landed item names consumer + behavior change. The
    # consumer is the IDA lane driver (tools/_index-static.md ida-decompile
    # row); the card must say what the agent DOES differently after reading.
    assert "ida-decompile" in text, "consumer lane must be named"
    assert re.search(
        r"behavior change|does differently|do differently", text, re.IGNORECASE
    ), "card must state the behavior change it causes"


def test_correction_overlays_and_compat_rows_present():
    text = _card_text()
    low = text.lower()
    # overlay 1: legacy idc -> modern ida_* migration map
    assert "idc" in low and re.search(r"ida_[a-z]", text), (
        "idc -> ida_* migration overlay expected"
    )
    # overlay 2: headless analysis-wait discipline
    assert "auto_wait" in low, "headless analysis-wait overlay expected"
    # overlay 3: Hex-Rays failure-channel edge behavior
    assert "decompile" in low, "Hex-Rays failure-edge overlay expected"
    # rule 10: version-compat audit rows (old -> break -> modern)
    assert "inf_get_" in low or "get_inf_structure" in low, (
        "rule-10 ida_ida accessor break row expected"
    )
    assert "ida_typeinf" in low, "rule-10 ida_typeinf rewrite row expected"


def test_cross_references_resolve():
    text = _card_text()
    links = re.findall(r"\]\(([^)#]+?\.md)\)", text)
    assert links, "house cards cross-reference siblings"
    for rel in links:
        target = ROOT / "references" / "re-library" / rel
        assert target.exists(), f"dangling cross-reference: {rel}"
