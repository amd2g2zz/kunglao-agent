# -*- coding: utf-8 -*-
"""tests/test_distill_dgate_365.py — the D-gate three-question lint
(issue 365, scope 5): a runtime note passes only if it answers the three
questions (why this plan order / situation→next-action branches / hidden
reasoning). Mechanical: sections present AND non-trivial.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from rlvr import distill_dgate as dg  # noqa: E402


def _note(sections: dict[str, str]) -> str:
    parts = ["# note: the frida-first plan"]
    for title, body in sections.items():
        parts.append(f"## {title}")
        parts.append(body)
    return "\n\n".join(parts) + "\n"


_FULL = {
    "why this plan order": "unpack before hook because the loader "
                           "re-encrypts sections on first run.",
    "situation to next action branches": "if attached, dump; if not, "
                                          "repack the gadget first.",
    "hidden reasoning": "the timing XOR poisons outputs only when a "
                        "debugger is present.",
}


class TestThreeQuestionLint:
    def test_full_note_passes(self):
        out = dg.lint_note(_note(_FULL))
        assert out["ok"] is True
        assert out["missing"] == []
        assert out["trivial"] == []

    def test_missing_section_fails(self):
        sections = dict(_FULL)
        del sections["hidden reasoning"]
        out = dg.lint_note(_note(sections))
        assert out["ok"] is False
        assert out["missing"] == ["hidden_reasoning"]

    def test_stub_section_is_trivial(self):
        sections = dict(_FULL)
        sections["hidden reasoning"] = "see above."
        out = dg.lint_note(_note(sections))
        assert out["ok"] is False
        assert out["trivial"] == ["hidden_reasoning"]

    def test_variant_headings_match(self):
        note = _note({
            "plan order rationale": _FULL["why this plan order"],
            "branch table": _FULL["situation to next action branches"],
            "reasoning not on the surface": _FULL["hidden reasoning"],
        })
        assert dg.lint_note(note)["ok"] is True

    def test_body_before_first_heading_never_counts(self):
        note = ("why this plan order unpack before hook\n\n"
                + _note({"branches": "x" * (dg.MIN_SECTION_CHARS + 1),
                         "hidden": "y" * (dg.MIN_SECTION_CHARS + 1)}))
        out = dg.lint_note(note)
        assert out["ok"] is False
        assert "plan_order" in out["missing"]


class TestSelfSourceSelection:
    def test_passing_notes_only(self, tmp_path):
        notes = tmp_path / "notes"
        notes.mkdir()
        (notes / "good.md").write_text(_note(_FULL), encoding="utf-8")
        (notes / "bad.md").write_text(
            _note({"branches": _FULL["situation to next action branches"]}),
            encoding="utf-8")
        picked = dg.passing_notes(tmp_path)
        assert [p.name for p in picked] == ["good.md"]

    def test_no_notes_dir_is_empty(self, tmp_path):
        assert dg.passing_notes(tmp_path) == []
