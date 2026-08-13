# -*- coding: utf-8 -*-
"""test_hook_exit_codes.py — verify exit-code semantic separation (#134)."""
from scripts.hook_exit_codes import ExitCode, HOOK_EXIT_SEMANTICS


def test_reject_and_blocked_are_distinct():
    assert ExitCode.REJECT != ExitCode.BLOCKED
    assert ExitCode.REJECT.value == 2
    assert ExitCode.BLOCKED.value == 3


def test_all_hooks_have_semantics():
    for hook in ["worker_budget", "worker_pulse", "state_anchor", "dispatch_gate"]:
        assert hook in HOOK_EXIT_SEMANTICS, f"missing semantics for {hook}"


def test_ok_is_zero():
    assert ExitCode.OK.value == 0
