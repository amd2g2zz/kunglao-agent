# -*- coding: utf-8 -*-
"""tests/test_orchestration_hardening.py — #309 misc hardening (absorbed ideas).

- tool error hysteresis (Rikugan loop.py:794-820 idea): same tool failing
  consecutively ≥3 → prompt, ≥5 → disable + escalate with blocker attribution
- CLAUDE_ENV_FILE mode (#304 init linkage): SessionStart hook reads a
  KEY=VALUE env file to supply environment — pure parser/loader here, the
  hook wiring belongs to the #304 init change
"""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import tool_error_policy as tep


# ---- tool error hysteresis -------------------------------------------------

def test_streak_below_threshold_is_ok():
    r = tep.evaluate_streak(2, tool="ghidra_decompile")
    assert r["action"] == "ok"
    assert r["streak"] == 2


def test_streak_three_warns():
    r = tep.evaluate_streak(3, tool="ghidra_decompile")
    assert r["action"] == "warn"
    assert "3" in r["message"]


def test_streak_five_disables_and_escalates():
    r = tep.evaluate_streak(5, tool="ghidra_decompile")
    assert r["action"] == "disable_escalate"
    assert r["blocker_note"]  # blocker attribution is recorded
    assert "ghidra_decompile" in r["blocker_note"]
    assert "5" in r["blocker_note"]


def test_streak_beyond_five_stays_disabled():
    assert tep.evaluate_streak(6, tool="t")["action"] == "disable_escalate"
    assert tep.evaluate_streak(9, tool="t")["action"] == "disable_escalate"


def test_exactly_four_is_still_warn():
    assert tep.evaluate_streak(4, tool="t")["action"] == "warn"


def test_thresholds_are_shared_constants():
    assert tep.WARN_THRESHOLD == 3
    assert tep.DISABLE_THRESHOLD == 5


def test_apply_policy_embeds_claim_for_blocker_attribution():
    r = tep.apply_policy("floss", 5, claim_id="C-003")
    assert r["action"] == "disable_escalate"
    assert "C-003" in r["blocker_note"]


