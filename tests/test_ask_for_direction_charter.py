#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_ask_for_direction_charter.py — 3-state charter (#447).

Covers the five types in references/agent-three-state-charter.md:
  - Type A (BAD ask-back) — REJECT (rc=1)
  - Type B (BAD completion-then-ask) — REJECT (rc=1)
  - Type C (OK convergence sign-off) — ALLOWED (rc=0)
  - Type D (must-ask: identity / scope / authorization) — HARD_PAUSE (rc=2)
  - Type S (must-stop: irreversible action) — HARD_PAUSE (rc=2)

Plus the original HARD_PAUSE on 3+ self-redirects.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import ask_for_direction_gate as afd  # noqa: E402


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A clean workspace with no prior self-redirect history."""
    return tmp_path


# ----- Type A (BAD ask-back) ----------------------------------------

class TestTypeA:
    def test_should_i_rejected(self, workspace: Path) -> None:
        rc = afd.check(workspace, "Done with C-1. Should I dispatch the next?")
        assert rc == 1

    def test_do_you_want_rejected(self, workspace: Path) -> None:
        rc = afd.check(workspace, "Do you want me to continue?")
        assert rc == 1

    def test_wait_user_decision_rejected(self, workspace: Path) -> None:
        # Use the keyword phrase that the regex actually matches.
        rc = afd.check(workspace, "please let me know next step")
        assert rc == 1

    def test_convergence_signal_overrides_type_a(self, workspace: Path) -> None:
        """Type A violation + Type C signal → ALLOWED (only at convergence)."""
        rc = afd.check(workspace,
                        "C0-C7 all pass, confirm convergence. "
                        "(should I dispatch more? — no, we converge)")
        assert rc == 0


# ----- Type B (BAD completion-then-ask) -----------------------------

class TestTypeB:
    def test_just_finished_should_i_rejected(self, workspace: Path) -> None:
        rc = afd.check(workspace, "Just finished C-1, should I move to C-2?")
        assert rc == 1


# ----- Type C (OK convergence sign-off) ------------------------------

class TestTypeC:
    def test_c0_c7_signoff_allowed(self, workspace: Path) -> None:
        rc = afd.check(workspace, "C0-C7 all converge, sign-off requested.")
        assert rc == 0


# ----- Chinese tripwire fixtures (non-exhaustive layer) ----------------

class TestChineseTripwires:
    """Sessions in this project produce Chinese output; the tripwire layer
    must cover the languages actually used. These are TRIPWIRES, not
    load-bearing enforcement (declaration-over-inference doctrine, #447):
    extending the list is routine, never a contract change."""

    def test_chinese_ask_back_rejected(self, workspace: Path) -> None:
        rc = afd.check(workspace, "等用户决定下一步怎么处理")
        assert rc == 1

    def test_chinese_completion_then_ask_rejected(self, workspace: Path) -> None:
        rc = afd.check(workspace, "刚才任务做完了，我要做下一个吗？")
        assert rc == 1


# ----- Type D (must-ask, #447 NEW) -----------------------------------

class TestTypeD:
    def test_identity_ambiguity_triggers_hard_pause(self, workspace: Path) -> None:
        rc = afd.check(workspace,
                        "Found multiple VMs matched the criteria, "
                        "which one should I use?")
        assert rc == 2

    def test_identity_ambiguity_keyword(self, workspace: Path) -> None:
        rc = afd.check(workspace, "identity ambiguity: target workspace unclear")
        assert rc == 2

    def test_authorization_boundary_new_hard_error(self, workspace: Path) -> None:
        rc = afd.check(workspace,
                        "encountered new blocker: toolchain mismatch. "
                        "Not in original scope.")
        assert rc == 2

    def test_scope_change_triggers_hard_pause(self, workspace: Path) -> None:
        rc = afd.check(workspace,
                        "This step is not covered by the task. Need direction.")
        assert rc == 2


# ----- Type S (must-stop, #447 NEW) ---------------------------------

class TestTypeS:
    def test_rm_vm_blocked(self, workspace: Path) -> None:
        rc = afd.check(workspace, "vmrun delete VM-1")
        assert rc == 2

    def test_git_push_force_blocked(self, workspace: Path) -> None:
        rc = afd.check(workspace, "git push --force to origin/main")
        assert rc == 2

    def test_snapshot_delete_blocked(self, workspace: Path) -> None:
        rc = afd.check(workspace, "snapshot delete + revert")
        assert rc == 2

    def test_publish_to_pypi_blocked(self, workspace: Path) -> None:
        rc = afd.check(workspace, "publish to pypi")
        assert rc == 2


# ----- Type S takes precedence over Type C (must-stop > allowed) -----

class TestPrecedence:
    def test_must_stop_beats_convergence(self, workspace: Path) -> None:
        """Even with Type C signal, an irreversible action MUST HARD_PAUSE."""
        rc = afd.check(workspace,
                        "C0-C7 converge, sign-off requested. "
                        "Now: git push --force")
        assert rc == 2

    def test_clean_orchestrator_output(self, workspace: Path) -> None:
        rc = afd.check(workspace,
                        "C-1 done. Dispatching C-2 next via priority.py.")
        assert rc == 0


# ----- HARD_PAUSE on 3+ self-redirects (legacy behaviour) ------------

class TestLegacyHardPause:
    def test_three_self_redirects_force_pause(self, workspace: Path) -> None:
        for i in range(3):
            afd.check(workspace, f"should I do thing {i}?")
        # 4th attempt should HARD_PAUSE (3 redirects in last hour)
        rc = afd.check(workspace, "should I do thing 3?")
        assert rc == 2


# ----- Self-redirect log shape ----------------------------------------

class TestRedirectLog:
    def test_log_file_is_jsonl(self, workspace: Path) -> None:
        afd.check(workspace, "should I do thing X?")
        log = workspace / afd.SELF_REDIRECT_LOG
        assert log.exists()
        lines = log.read_text(encoding="utf-8").strip().splitlines()
        assert lines, "log must have at least one entry"
        ev = json.loads(lines[0])
        assert "ts" in ev
        assert "violation" in ev
        assert "excerpt" in ev