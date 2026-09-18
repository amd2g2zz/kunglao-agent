# -*- coding: utf-8 -*-
"""Method-selection split for the reproduction oracle (#248 post2 slim
scope, owner ruling 2026-09-18). Two kept pieces:

  1. intake maps generation-language to the reproduction oracle and
     refuses the observational selections for an algorithm-class goal
     (scripts/oracle_anchors.py)
  3. evidence settles by need (scripts/settle_by_need.py — exercised in
     tests/test_settle_by_need.py)

Piece 2 (closed-book reproduction admission/verdict machinery in
scripts/replay_equivalence.py: reproduction_client execution,
verifier-sampled novel inputs, source-derived reference) was CUT to
issue #259 (v0.1.6) — no test here may import replay_equivalence.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import oracle_anchors  # noqa: E402


# ------------------------------------------- 1. intake: generation-language

@pytest.mark.parametrize("goal", [
    "签名参数是怎么生成的",
    "这个签名字段是怎么算出来的",
    "签名算法的什么原理",
    "请求是如何构造的",
    "how is the signature computed",
    "how is it generated",
    "what algorithm generates the token",
])
def test_generation_language_is_detected(goal):
    assert oracle_anchors.is_generation_language(goal)


@pytest.mark.parametrize("goal", [
    "登录接口能返回 200",
    "replay the captured request successfully",
    "接口是否可访问",
    # declarative passives are statements, not algorithm-class asks —
    # the bare "is computed"-style substrings were dropped (#248 post2
    # review LOW note); only interrogative forms classify
    "the signature is computed server-side",
    "check the output is generated within 100ms",
])
def test_acceptance_language_is_not_generation(goal):
    assert not oracle_anchors.is_generation_language(goal)


def test_intake_pins_reproduction_for_algorithm_class():
    spec = {"goal_verbatim": "签名参数是怎么生成的",
            "success_criterion": "closed-book reproduction matches",
            "verification_method": "replay-evidence"}
    assert oracle_anchors.derive_verification_method(spec) == "reproduction"


def test_intake_pins_reproduction_for_generation_english_goal():
    spec = {"goal_verbatim": "how is the signature computed",
            "success_criterion": "x",
            "verification_method": "replay-evidence"}
    assert oracle_anchors.derive_verification_method(spec) == "reproduction"


def test_intake_keeps_spec_answer_for_acceptance_class():
    spec = {"goal_verbatim": "登录接口能返回 200",
            "success_criterion": "x",
            "verification_method": "replay-evidence"}
    assert oracle_anchors.derive_verification_method(spec) == "replay-evidence"


def test_intake_refuses_weak_selection_for_algorithm_class():
    spec = {"goal_verbatim": "签名参数是怎么生成的",
            "success_criterion": "x",
            "verification_method": "replay-evidence"}
    ok, reason = oracle_anchors.intake_method_gate(spec)
    assert not ok
    assert "replay-evidence" in reason


@pytest.mark.parametrize("weak", ["static", "manual"])
def test_intake_refuses_every_observational_method(weak):
    spec = {"goal_verbatim": "请求是如何构造的",
            "success_criterion": "x",
            "verification_method": weak}
    ok, reason = oracle_anchors.intake_method_gate(spec)
    assert not ok
    assert weak in reason


def test_intake_gate_allows_replay_for_acceptance_class():
    spec = {"goal_verbatim": "登录接口能返回 200",
            "success_criterion": "x",
            "verification_method": "replay-evidence"}
    ok, reason = oracle_anchors.intake_method_gate(spec)
    assert ok, reason


def test_intake_gate_allows_reproduction_for_algorithm_class():
    spec = {"goal_verbatim": "签名参数是怎么生成的",
            "success_criterion": "x",
            "verification_method": "reproduction"}
    ok, reason = oracle_anchors.intake_method_gate(spec)
    assert ok, reason


# --------------------------------- wiring: the gates live on the real faces

def test_validate_values_refuses_weak_method_for_algorithm_goal():
    """Piece 1 wiring: the intake pre-write contract refuses to LAND the
    weak selection for a generation-language goal (kunglao-init /
    kunglao-upgrade call validate_values before oracle_anchors.apply)."""
    values = {"goal_verbatim": "签名参数是怎么生成的",
              "success_criterion": "x",
              "verification_method": "replay-evidence"}
    with pytest.raises(ValueError) as exc:
        oracle_anchors.validate_values(values)
    assert "replay-evidence" in str(exc.value)
    # the pinned method and an acceptance-class goal land unchanged
    oracle_anchors.validate_values({**values,
                                    "verification_method": "reproduction"})
    oracle_anchors.validate_values({"goal_verbatim": "登录接口能返回 200",
                                    "verification_method": "replay-evidence"})
