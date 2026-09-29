# -*- coding: utf-8 -*-
"""tests/test_v0_retirement_861.py — #861 v0 退役落地合同测试。

v0 retirement COMPLETED (compat-rot sweep 2026-09-29, audit B2 / owner
ruling D2): the parse face stops ACCEPTING the v0 claim prefix —
canonical v1 envelope is the only recognized claim dispatch across
recall / worker_pulse / worker_budget_core; all three parsers extract the
same (tier, tools, claim) from v1 and REJECT v0 text. The local v0 regex
copy is retired with the single source (lib_kunglao DISPATCH_RE deleted).

Boundary (#137 code-vs-data): historical v0 rows in runs/logs are
WORKSPACE DATA — replay-readers match them by substring/literal, never
through the parse face; this test pins code, not data.
"""
from __future__ import annotations

from pathlib import Path


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


def test_v0_prefix_is_no_longer_a_claim_dispatch():
    """v0 retirement completed: the recall face rejects the legacy prefix
    (was: pinned as accepted — the rot-preserving form, re-minted)."""
    assert recall_inject._is_claim_dispatch(V0_PREFIX) is False


def test_plain_text_not_claim():
    assert recall_inject._is_claim_dispatch("no dispatch here at all") is False


def test_worker_pulse_was_dispatch_v1():
    assert worker_pulse._was_dispatch(
        {"tool_input": {"prompt": V1_ENVELOPE}}) is True


def test_worker_pulse_was_dispatch_v0_rejected():
    """v0 retirement completed: the pulse no longer fires on the legacy
    prefix — a fresh v0-form dispatch is invisible to the loop (the only
    sanctioned producer emits v1, see blind_gate remediation prose)."""
    assert worker_pulse._was_dispatch(
        {"tool_input": {"prompt": V0_PREFIX}}) is False


def test_budget_parse_dispatch_v1():
    tier, tools, cid = worker_budget_core.parse_dispatch(V1_ENVELOPE)
    assert (tier, tools, cid) == (1, ["pe_analyze", "strings-classify"], "C-409")


def test_budget_parse_dispatch_v0_rejected():
    """v0 retirement completed: the claim-form v0 prefix parses to absent.
    The claim-LESS bare-prefix edge (init-worker class) is the local budget
    contract pinned in test_worker_budget, not here."""
    tier, tools, cid = worker_budget_core.parse_dispatch(V0_PREFIX)
    assert (tier, tools, cid) == (0, [], None)


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


def test_three_parser_consistency_on_v0_rejection():
    """v0 retirement completed: all three parsers agree v0 is absent —
    no parser keeps a private legacy-acceptance path."""
    assert _lib.parse_dispatch(V0_PREFIX) == (0, [], None)
    assert worker_budget_core.parse_dispatch(V0_PREFIX) == (0, [], None)
    assert recall_inject._is_claim_dispatch(V0_PREFIX) is False


def test_skill_md_teaches_v1_envelope():
    """SKILL 教的形状 = v1（kunglao_dispatch 出现在 dispatch contract 节）。"""
    skill = (ROOT / "skills" / "kunglao-agent" / "SKILL.md").read_text(
        encoding="utf-8")
    assert "kunglao_dispatch" in skill
    assert "## The dispatch contract" in skill


def test_lib_has_no_v0_regex_single_source():
    """The v0 regex is deleted from the single source (retirement-gate
    owner) — no DISPATCH_RE identifier survives in hooks/ or scripts/
    (retirement_gate.py keeps scanning for stray copies)."""
    assert not hasattr(_lib, "DISPATCH_RE")
