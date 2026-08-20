# -*- coding: utf-8 -*-
"""tests/test_pr_template_530.py — issue #530 disposition lock:
PR template carries the anti-orphan double question.

Prevents the ship-then-orphan pattern (#530; umbrella cross-cutting
constraint #4 "no new dead code"): every PR that adds or moves code must
name the runtime consumer and the writing state transition.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _find_template() -> Path | None:
    candidates = [
        ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md",
        ROOT / ".github" / "pull_request_template.md",
        ROOT / "docs" / "PULL_REQUEST_TEMPLATE.md",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def test_pr_template_exists():
    tmpl = _find_template()
    assert tmpl is not None, "PR template not found in any expected location"


def test_pr_template_has_anti_orphan_questions():
    tmpl = _find_template()
    assert tmpl is not None, "PR template not found"
    text = tmpl.read_text(encoding="utf-8").lower()
    has_consumer = any(
        phrase in text
        for phrase in ("who reads this at runtime", "谁在运行时读", "runtime consumer")
    )
    has_writer = any(
        phrase in text
        for phrase in (
            "what state transition writes this",
            "什么状态迁移写",
            "state transition",
        )
    )
    assert has_consumer, "PR template missing 'who reads at runtime?' question"
    assert has_writer, "PR template missing 'what state writes this?' question"
