# -*- coding: utf-8 -*-
"""tests/test_v0_retirement_861.py — #861 v0 退役落地合同测试。

单源化后合同：canonical v1 envelope 与 v0 legacy prefix 都必须被
recall 检测 / worker_pulse / worker_budget_core 三处识别，且三 parser
对同一输入提取同一 (tier, tools, claim)；本地 v0 正则副本退役。
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

from _path_hygiene import load_hooks_lib  # noqa: E402  (pytest.ini pythonpath)

_lib = load_hooks_lib()
import recall_inject  # noqa: E402
import worker_pulse  # noqa: E402
import worker_budget_core  # noqa: E402

V1_ENVELOPE = (
    '{"kunglao_dispatch": {"version": 1, "claim": "C-409", '
    '"tier": 1, "tools": ["pe_analyze", "strings-classify"], '
    '"agent": "ghidra-light"}}\nrest of prompt'
)
V0_PREFIX = "[T1 tools=grep,xxd] claim C-007 grep chemistry strings"


def test_v1_envelope_trips_recall_claim_detection():
    assert recall_inject._is_claim_dispatch(V1_ENVELOPE) is True


def test_v0_prefix_still_trips_recall_detection_legacy():
    assert recall_inject._is_claim_dispatch(V0_PREFIX) is True


def test_plain_text_not_claim():
    assert recall_inject._is_claim_dispatch("no dispatch here at all") is False


def test_worker_pulse_was_dispatch_v1():
    assert worker_pulse._was_dispatch(
        {"tool_input": {"prompt": V1_ENVELOPE}}) is True


def test_worker_pulse_was_dispatch_v0_legacy():
    assert worker_pulse._was_dispatch(
        {"tool_input": {"prompt": V0_PREFIX}}) is True


def test_budget_parse_dispatch_v1():
    tier, tools, cid = worker_budget_core.parse_dispatch(V1_ENVELOPE)
    assert (tier, tools, cid) == (1, ["pe_analyze", "strings-classify"], "C-409")


def test_budget_parse_dispatch_v0_legacy():
    tier, tools, cid = worker_budget_core.parse_dispatch(V0_PREFIX)
    assert (tier, tools, cid) == (1, ["grep", "xxd"], "C-007")


def test_budget_parse_dispatch_absent():
    assert worker_budget_core.parse_dispatch("plain text") == (0, [], None)


def test_three_parser_consistency_on_v1():
    """canonical v1 → 三 parser 提取同一 (tier, tools, claim) (#861 合同)。"""
    lib_t, lib_tools, lib_cid = _lib.parse_dispatch(V1_ENVELOPE)
    b_t, b_tools, b_cid = worker_budget_core.parse_dispatch(V1_ENVELOPE)
    recall_ok = recall_inject._is_claim_dispatch(V1_ENVELOPE)
    assert (lib_t, lib_tools, lib_cid) == (b_t, b_tools, b_cid)
    assert recall_ok is True
    assert lib_cid == "C-409"


def test_skill_md_teaches_v1_envelope():
    """SKILL 教的形状 = v1（kunglao_dispatch 出现在 dispatch contract 节）。"""
    skill = (ROOT / "skills" / "kunglao-agent" / "SKILL.md").read_text(
        encoding="utf-8")
    assert "kunglao_dispatch" in skill
    assert "## The dispatch contract" in skill
