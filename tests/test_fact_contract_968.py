# -*- coding: utf-8 -*-
"""tests/test_fact_contract_968.py — the fact-writer↔lint conformance pins
(issue #968: live sessions wrote F-001-style facts because the workspace
CLAUDE.md taught a shape the lint refuses; the writer instruction and the
lint rules must be ONE contract).

Pins:
  1. The shipped example in templates/fact-frontmatter.md passes
     lint_facts.lint_fact with ZERO error issues — the template IS the
     contract, so its own example must be clean.
  2. The workspace CLAUDE.md base template no longer recommends the
     bare `F<NNN>`/`F-001` shapes; every concrete fact id it shows is
     ID_RE-valid, and it defers the field contract to the template file.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import lint_facts  # noqa: E402


def _template_text() -> str:
    return (ROOT / "templates" / "CLAUDE.md.base.tmpl").read_text(
        encoding="utf-8")


def _frontmatter_example() -> tuple[str, dict]:
    """The complete frontmatter example block from
    templates/fact-frontmatter.md (the block that starts with ---)."""
    text = (ROOT / "templates" / "fact-frontmatter.md").read_text(
        encoding="utf-8")
    blocks = re.findall(r"```yaml\n(.*?)```", text, re.S)
    fm_blocks = [b for b in blocks if b.strip().startswith("---")]
    assert fm_blocks, "fact-frontmatter.md lost its frontmatter example"
    lines = fm_blocks[0].strip().splitlines()
    assert lines[0].strip() == "---"
    end = next(i for i in range(1, len(lines))
               if lines[i].strip() == "---")
    fm = yaml.safe_load("\n".join(lines[1:end]))
    return str(fm["id"]), fm


def test_shipped_example_passes_lint_clean() -> None:
    """The template's own example is the writer-side ground truth: it
    must land with ZERO error-level lint issues (warnings allowed —
    e.g. the staleness notice on a dated example)."""
    fid, fm = _frontmatter_example()
    issues = lint_facts.lint_fact(fid, fm, {fid}, body="")
    errors = [i for i in issues if i[0] == "error"]
    assert not errors, (
        "the shipped fact-frontmatter example fails its own lint — the "
        f"writer contract and the lint have drifted: {errors}")


def test_base_template_ids_are_id_re_valid() -> None:
    """Every concrete `F...` id shape the base template shows must be
    ID_RE-valid; the refused bare shapes must not recommend writing."""
    text = _template_text()
    # the refused shape must never be the recommended form
    assert "facts/F<NNN>.md" not in text, (
        "the base template still teaches facts/F<NNN>.md — the exact "
        "shape live sessions copied and the lint refuses")
    assert "`id: F<NNN>`" not in text, (
        "the base template still shows the bare `id: F<NNN>` frontmatter")
    # concrete id mentions (digit-bearing) must be ID_RE-valid
    for m in re.finditer(r"\bF\d{3,}[a-z0-9-]*\b", text):
        assert lint_facts.ID_RE.fullmatch(m.group(0)), (
            f"the base template shows invalid fact id {m.group(0)!r}")


def test_base_template_defers_to_the_frontmatter_template() -> None:
    """The base template must point the writer at the authoritative
    contract file instead of re-listing the field set (the re-listing
    is what drifted)."""
    text = _template_text()
    assert ".claude/templates/fact-frontmatter.md" in text
    assert "REFUSED by the lint" in text, (
        "the base template must name the refused shape explicitly")


def test_refused_live_shape_is_really_refused() -> None:
    """The shape the live sessions actually wrote (`F-001`) must fail
    ID_RE — pinning that the fixed instructions and the lint agree on
    the refusal."""
    assert lint_facts.ID_RE.fullmatch("F-001") is None
    assert lint_facts.ID_RE.fullmatch("F001-first-finding") is not None
