# -*- coding: utf-8 -*-
"""tests/test_pdl_collapse_582.py — #582: the 1-caller PendingDecisionList
wrapper collapses to module functions.

Ponytail (yagni): PendingDecisionList had exactly one production caller
(kunglao-init.py:881) plus its own test — the dataclass bought nothing over
module-level to_json(). Fix: keep the shape (the JSON contract is pinned by
the #449/#455 flow) but collapse the class into a build_pending_doc() +
pending_doc_json() function pair; the single caller and the test move with it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import decision_pending as dp  # noqa: E402


def _sample_doc() -> dict:
    return dp.build_pending_doc(
        flow="kunglao-init",
        workspace="/tmp/ws",
        guidance="re-enter with --resolve",
        decisions=[dp.PendingDecision(
            decision_id="workspace", question="which workspace?",
            kind="path", options=[], default=None,
            context={"from_probe": True})],
        resume={"cmd": "kunglao-init --resolve"})


def test_build_pending_doc_shape():
    payload = json.loads(dp.pending_doc_json(_sample_doc()))
    assert payload["schema_version"] == dp.SCHEMA_VERSION
    assert payload["flow"] == "kunglao-init"
    assert payload["decisions"][0]["decision_id"] == "workspace"
    assert payload["decisions"][0]["context"] == {"from_probe": True}
    assert payload["resume"] == {"cmd": "kunglao-init --resolve"}


def test_class_gone_single_caller_collapsed():
    src = (ROOT / "scripts" / "decision_pending.py").read_text(encoding="utf-8")
    assert "class PendingDecisionList" not in src, \
        "the 1-caller wrapper collapses to functions (ponytail #582)"
    init_src = (ROOT / "scripts" / "kunglao-init.py").read_text(encoding="utf-8")
    assert "PendingDecisionList" not in init_src, "caller uses the function pair"
