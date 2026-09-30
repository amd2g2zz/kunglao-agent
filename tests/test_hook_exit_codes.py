# -*- coding: utf-8 -*-
"""test_hook_exit_codes.py — verify exit-code semantic separation (#134).

#472 MEDIUM: extended to pin the completion_gate vocabulary (0-7), the
workguard/completion_gate registry rows, and the shim-constant derivation
(the registry is the single source of truth; the drift-guard role over the
shim's PRIMARY path lives here — test_notes_closure_762's substring pin
keeps covering the fallback literal)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from scripts.hook_exit_codes import ExitCode, HOOK_EXIT_SEMANTICS

HOOKS = Path(__file__).resolve().parents[1] / "hooks"


def test_reject_and_blocked_are_distinct():
    assert ExitCode.REJECT != ExitCode.BLOCKED
    assert ExitCode.REJECT.value == 2
    assert ExitCode.BLOCKED.value == 3


def test_all_hooks_have_semantics():
    for hook in ["worker_budget", "worker_pulse", "state_anchor", "dispatch_gate", "env_check_gate"]:
        assert hook in HOOK_EXIT_SEMANTICS, f"missing semantics for {hook}"


def test_ok_is_zero():
    assert ExitCode.OK.value == 0


# ---------------------------------------------------------------------------
# #472 — registry completeness + the shim derivation pin
# ---------------------------------------------------------------------------

def test_blocking_hooks_are_registered():
    """Every hook that can block must carry a registry row (#472): the
    completion gate (exit 1-7 vocabulary) and the workguard (exit 1 block
    face) were unregistered."""
    for hook in ("completion_gate", "workguard_gate"):
        assert hook in HOOK_EXIT_SEMANTICS, f"missing semantics for {hook}"


def test_exit_codes_four_to_seven_are_pinned_members():
    """The completion-gate-only codes exist as registry members with the
    shim's pinned values (no drift between enum and hook constants)."""
    assert int(ExitCode.INTENT_UNMATCHED) == 4
    assert int(ExitCode.NOTES_DUE) == 5
    assert int(ExitCode.NOTES_FAKE) == 6
    assert int(ExitCode.SUMMARY_FAKE) == 7


def test_completion_gate_row_documents_full_vocabulary():
    """Every code the judge (0-4) or the shim (1/3/5/6/7) can emit is
    documented, and exit 1 is documented as a deliberate fail-closed
    block — NOT a crash (#472 exit-1 dual-meaning resolution)."""
    sem = HOOK_EXIT_SEMANTICS["completion_gate"]
    documented = {int(code) for code in sem}
    assert documented == {0, 1, 2, 3, 4, 5, 6, 7}
    assert "deliberate" in sem[ExitCode.GENERAL_ERROR].lower()
    assert "not a crash" in sem[ExitCode.GENERAL_ERROR].lower()


def test_shim_exit_constants_derive_from_registry():
    """The shim's EXIT_* constants equal the registry members AND the
    pinned literals — the registry is the single source of truth, with
    the literal preserved in the fail-open fallback arm (which is what
    test_notes_closure_762's substring pin covers)."""
    spec = importlib.util.spec_from_file_location(
        "completion_gate_hook_472", HOOKS / "completion_gate.py")
    shim = importlib.util.module_from_spec(spec)
    sys.modules["completion_gate_hook_472"] = shim
    spec.loader.exec_module(shim)
    assert shim.EXIT_NOTES_DUE == int(ExitCode.NOTES_DUE) == 5
    assert shim.EXIT_NOTES_FAKE == int(ExitCode.NOTES_FAKE) == 6
    assert shim.EXIT_SUMMARY_FAKE == int(ExitCode.SUMMARY_FAKE) == 7
    shim_src = (HOOKS / "completion_gate.py").read_text(encoding="utf-8")
    assert "EXIT_NOTES_DUE = 5" in shim_src  # fallback literal survives
