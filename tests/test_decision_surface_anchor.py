#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_decision_surface_anchor.py — F-class decision-surface
machine anchor (issue #446, comment 2026-08-19).

The charter (references/agent-three-state-charter.md) declares itself THE
single source for the three states; scripts/error_response.py carries a
derived column (_CHARTER_STATE). Before this anchor the cross-reference
was prose-only — nothing mechanical failed when one side drifted.

Anchor shape (symbolic, NOT line numbers — issue #446 acceptance says
line references must be replaced by symbol references):
  - error_response.py declares CHARTER_SOURCE + CHARTER_STATES
  - the charter's executor table names error_response.py back
  - this test asserts MUTUAL PRESENCE on both faces, plus value-domain
    lockstep (_CHARTER_STATE tokens drawn from the charter vocabulary)
    and class-name lockstep with the taxonomy table
    (references/error-response-taxonomy.md).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import error_response as er  # noqa: E402

CHARTER = REPO_ROOT / "references" / "agent-three-state-charter.md"
TAXONOMY = REPO_ROOT / "references" / "error-response-taxonomy.md"


class TestCharterStatesDeclaration:
    def test_source_and_states_declared(self) -> None:
        assert er.CHARTER_SOURCE == "references/agent-three-state-charter.md"
        assert set(er.CHARTER_STATES) == {"allowed", "must-ask", "must-stop"}

    def test_charter_state_values_draw_from_charter_vocabulary(self) -> None:
        """Every _CHARTER_STATE entry's leading token must be one of the
        charter's three states (annotations after '(' or '->' are allowed
        context, e.g. 'must-ask (escalate via Type D)')."""
        for cls, state in er._CHARTER_STATE.items():
            token = re.split(r"\s*(?:\(|->)", state)[0].strip()
            assert token in er.CHARTER_STATES, (
                f"{cls}: charter_state {state!r} starts with {token!r}, "
                f"which is not charter vocabulary {er.CHARTER_STATES}")


class TestMutualAnchor:
    def test_charter_names_error_response_as_executor(self) -> None:
        """Face 1 of the mutual anchor: the charter's executor table must
        name error_response.py (a derived column of the three-state table)."""
        text = CHARTER.read_text(encoding="utf-8")
        assert "error_response.py" in text, (
            "charter no longer names scripts/error_response.py — the "
            "decision-surface anchor is one-sided (F-class, #446)")

    def test_charter_declares_all_three_states(self) -> None:
        text = CHARTER.read_text(encoding="utf-8")
        for state in er.CHARTER_STATES:
            assert state in text, f"charter lost state {state!r}"

    def test_error_response_names_charter_source(self) -> None:
        """Face 2 of the mutual anchor: the code side must point at the
        charter file (single-source citation, not a copied table)."""
        src = (REPO_ROOT / "scripts" / "error_response.py").read_text(encoding="utf-8")
        assert "agent-three-state-charter.md" in src


class TestTaxonomyLockstep:
    def test_every_error_class_appears_in_taxonomy_table(self) -> None:
        """Class-name lockstep: each ErrorClass value must exist as a row in
        the taxonomy's classification table. UNCLASSIFIED is labelled in
        Chinese in the doc (未分类) — mapped explicitly, not guessed."""
        tax = TAXONOMY.read_text(encoding="utf-8")
        label = {"UNCLASSIFIED": "未分类"}
        for cls in er.ErrorClass:
            needle = label.get(cls.value, cls.value)
            assert needle in tax, (
                f"ErrorClass {cls.value!r} has no row in "
                f"references/error-response-taxonomy.md — table drift")

    def test_taxonomy_names_its_mechanical_executor(self) -> None:
        tax = TAXONOMY.read_text(encoding="utf-8")
        assert "error_response.py" in tax

    def test_error_response_names_taxonomy_doc(self) -> None:
        src = (REPO_ROOT / "scripts" / "error_response.py").read_text(encoding="utf-8")
        assert "error-response-taxonomy.md" in src
