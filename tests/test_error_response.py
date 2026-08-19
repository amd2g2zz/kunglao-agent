#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_error_response.py — issue #448 error response taxonomy.

Covers:
  - Mechanical classification (vmrun / init-exit / tool-install)
  - All 9 ErrorClasses covered (table completeness)
  - Issue #448 evidence-2 fixtures (T1..T4)
  - Acceptance criterion (init exit 4 → STOP + allowed_actions excludes
    'proxy_repair' / 'continue_silently')
  - CLI exit code 2 on UNCLASSIFIED (LLM backstop signal)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import error_response as er  # noqa: E402
from error_response import (  # noqa: E402
    Classification,
    ErrorClass,
    Response,
    classify_init_exit,
    classify_vmrun,
)


# ---------- Mechanical classifier fixtures --------------------------

class TestVmrunClassification:
    def test_config_change_required_chinese(self) -> None:
        c = classify_vmrun("vmrun start 操作被取消 — 加电失败")
        assert c.klass is ErrorClass.CONFIG_CHANGE_REQUIRED
        assert c.response is Response.ASK
        assert "change_config_silently" in c.forbidden_actions

    def test_config_change_required_english(self) -> None:
        c = classify_vmrun("vmrun: operation cancelled by user")
        assert c.klass is ErrorClass.CONFIG_CHANGE_REQUIRED

    def test_channel_failure(self) -> None:
        c = classify_vmrun("runProgramInGuest hang — guest not responding")
        assert c.klass is ErrorClass.CHANNEL_FAILURE
        assert c.response is Response.ESCALATE

    def test_channel_failure_chinese(self) -> None:
        c = classify_vmrun("通道挂死 — guest 无响应")
        assert c.klass is ErrorClass.CHANNEL_FAILURE

    def test_identity_ambiguity(self) -> None:
        c = classify_vmrun("multiple VMs matched the criterion")
        assert c.klass is ErrorClass.IDENTITY_AMBIGUITY
        assert c.response is Response.ASK

    def test_identity_ambiguity_chinese(self) -> None:
        c = classify_vmrun("发现多个 vm 匹配条件")
        assert c.klass is ErrorClass.IDENTITY_AMBIGUITY

    def test_transient_lock(self) -> None:
        c = classify_vmrun("error: file is locked by another process")
        assert c.klass is ErrorClass.TRANSIENT_LOCK
        assert c.response is Response.RETRY_ONCE
        assert "delete_lock" in c.forbidden_actions

    def test_transient_lock_chinese(self) -> None:
        c = classify_vmrun("文件正在使用中,无法访问")
        assert c.klass is ErrorClass.TRANSIENT_LOCK

    def test_transient_timeout(self) -> None:
        c = classify_vmrun("connection reset by peer (timeout)")
        assert c.klass is ErrorClass.TRANSIENT_TIMEOUT

    def test_review_gate_blocked_human_event(self) -> None:
        """A review-gate BLOCKED stderr takes precedence over vmrun signals
        (it's a charter-level STOP, not a vmrun retry)."""
        c = classify_vmrun("REVIEW GATE BLOCKED: evidence invalid or stale")
        assert c.klass is ErrorClass.HUMAN_EVENT_REFUSE
        assert c.response is Response.STOP

    def test_unclassified_defaults_to_ask(self) -> None:
        c = classify_vmrun("some completely unknown phrasing")
        assert c.klass is ErrorClass.UNCLASSIFIED
        # Default safest: ASK — per "机械漏召回 → ASK" doctrine
        assert c.response is Response.ASK


class TestInitExitClassification:
    def test_exit_3_human_event(self) -> None:
        c = classify_init_exit(3)
        assert c.klass is ErrorClass.HUMAN_EVENT_REFUSE
        assert c.response is Response.STOP

    def test_exit_4_human_event(self) -> None:
        """Issue #448 evidence 2 T1 + acceptance #3 fixture."""
        c = classify_init_exit(4)
        assert c.klass is ErrorClass.HUMAN_EVENT_REFUSE
        assert c.response is Response.STOP
        # Hard priority: agent MUST NOT proxy-repair or continue silently
        assert "proxy_repair" in c.forbidden_actions
        assert "continue_silently" in c.forbidden_actions

    def test_exit_7_pending_decisions(self) -> None:
        c = classify_init_exit(7)
        assert c.klass is ErrorClass.PENDING_DECISIONS
        assert c.response is Response.ASK

    def test_exit_8_pending_decisions(self) -> None:
        c = classify_init_exit(8)
        assert c.klass is ErrorClass.PENDING_DECISIONS
        assert c.response is Response.ASK

    def test_exit_0_unclassified(self) -> None:
        c = classify_init_exit(0)
        assert c.klass is ErrorClass.UNCLASSIFIED


class TestToolInstallClassification:
    def test_hard_fail(self) -> None:
        c = er.classify_tool_install(
            "die: install declined/failed; HARD item stays")
        assert c.klass is ErrorClass.TOOL_INSTALL_HARD_FAIL
        assert c.response is Response.STOP
        assert "degrade_and_continue" in c.forbidden_actions

    def test_unknown_unclassified(self) -> None:
        c = er.classify_tool_install("some warning text")
        assert c.klass is ErrorClass.UNCLASSIFIED


# ---------- Table completeness -------------------------------------- --------

class TestTableCompleteness:
    """Every ErrorClass MUST appear in all five tables. Adding a new class
    without updating the tables is a CI failure — this test is the gate."""

    def test_response_map_covers_all_classes(self) -> None:
        for cls in ErrorClass:
            assert cls in er._RESPONSE_MAP, \
                f"ErrorClass {cls} missing from _RESPONSE_MAP"

    def test_charter_state_covers_all_classes(self) -> None:
        for cls in ErrorClass:
            assert cls in er._CHARTER_STATE

    def test_rationale_covers_all_classes(self) -> None:
        for cls in ErrorClass:
            assert cls in er._RATIONALE
            assert er._RATIONALE[cls].strip(), f"empty rationale for {cls}"

    def test_allowed_actions_covers_all_classes(self) -> None:
        for cls in ErrorClass:
            assert cls in er._ALLOWED
            assert len(er._ALLOWED[cls]) > 0, \
                f"empty allowed_actions for {cls}"

    def test_forbidden_actions_covers_all_classes(self) -> None:
        for cls in ErrorClass:
            assert cls in er._FORBIDDEN
            assert len(er._FORBIDDEN[cls]) > 0, \
                f"empty forbidden_actions for {cls}"


# ---------- Acceptance criterion: priority over default-allowed rule ----

class TestPriorityOverDefaultAllowed:
    """#448 priority statement: human-event-refuse MUST STOP regardless of
    the 'default allowed' rule (charter hard-prohibition #1)."""

    def test_exit_4_stops_and_forbids_proxy_repair(self) -> None:
        c = classify_init_exit(4)
        # Even though the charter default is 'allowed' (no asks), the
        # human-event gate overrides → STOP.
        assert c.response is Response.STOP, \
            "priority statement broken: init exit 4 must STOP"
        assert "proxy_repair" in c.forbidden_actions, \
            "agent MUST NOT proxy-repair a HARD REFUSE"
        assert "continue_silently" in c.forbidden_actions, \
            "agent MUST NOT continue silently past HARD REFUSE"
        # And the charter_state surfaces this as must-stop
        assert "must-stop" in c.charter_state


# ---------- CLI subprocess tests ---------------------------------------

class TestCLI:
    SCRIPT = REPO_ROOT / "scripts" / "error_response.py"

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(self.SCRIPT), *args],
            capture_output=True, text=True, timeout=15, cwd=REPO_ROOT,
            errors="replace",
        )

    def test_cli_classify_vmrun_exit_zero(self) -> None:
        r = self._run("classify", "--kind", "vmrun",
                       "--stderr", "操作被取消")
        assert r.returncode == 0
        assert "CONFIG-CHANGE-REQUIRED" in r.stdout

    def test_cli_classify_unclassified_exit_two(self) -> None:
        """rc=2 is the LLM-backstop signal — caller knows classification
        is uncertain and may invoke a semantic review."""
        r = self._run("classify", "--kind", "vmrun",
                       "--stderr", "completely unknown phrasing")
        assert r.returncode == 2
        assert "UNCLASSIFIED" in r.stdout

    def test_cli_classify_init_exit_4_exit_zero(self) -> None:
        r = self._run("classify", "--kind", "init-exit",
                       "--exit-code", "4", "--json")
        assert r.returncode == 0
        data = json.loads(r.stdout.strip())
        assert data["class"] == "HUMAN-EVENT-REFUSE"
        assert data["response"] == "STOP"
        assert data["charter_state"] == "must-stop"

    def test_cli_classify_init_exit_8_ask(self) -> None:
        r = self._run("classify", "--kind", "init-exit",
                       "--exit-code", "8", "--json")
        assert r.returncode == 0
        data = json.loads(r.stdout.strip())
        assert data["class"] == "PENDING-DECISIONS"
        assert data["response"] == "ASK"

    def test_cli_no_args_usage_error(self) -> None:
        r = self._run()
        assert r.returncode != 0


# ---------- Library dataclass properties -------------------------------

class TestClassificationProperties:
    def test_response_property_derives_from_table(self) -> None:
        c = classify_vmrun("操作被取消")
        assert c.response is Response.ASK
        assert "must-ask" in c.charter_state
        assert c.allowed_actions == ["ask_user"]
        assert "change_config_silently" in c.forbidden_actions

    def test_unclassified_ask_default(self) -> None:
        c = classify_vmrun("xyzzy frobozz magic")
        # Default safest: ASK
        assert c.klass is ErrorClass.UNCLASSIFIED
        assert c.response is Response.ASK
        assert "continue_silently" in c.forbidden_actions
        assert "self_resolve" in c.forbidden_actions