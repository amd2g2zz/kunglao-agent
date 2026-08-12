"""Tests for scripts/check_global_rule_subset.py.

Issue #99 D14: Validates that the global-rule hard prohibitions
(rules/kunglao-convergence-loop.md section 7) and SKILL.md Hard prohibitions
have bidirectional coverage -- no gaps in either direction.

RED phase: these tests define the expected behavior of the check script.
GREEN phase: the check script satisfies all invariants.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_global_rule_subset.py"
SKILL_MD = ROOT / "SKILL.md"
GLOBAL_RULE = ROOT / "rules" / "kunglao-convergence-loop.md"


# ---------------------------------------------------------------------------
# Helper: run the check script, return (returncode, stdout, stderr)
# ---------------------------------------------------------------------------


def _run_check(
    skill_md: Path | None = None,
    global_rule: Path | None = None,
) -> tuple[int, str, str]:
    """Invoke check_global_rule_subset.py with optional overrides."""
    cmd = [sys.executable, str(SCRIPT)]
    if skill_md is not None:
        cmd.extend(["--skill", str(skill_md)])
    if global_rule is not None:
        cmd.extend(["--global-rule", str(global_rule)])
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# Parsing unit tests -- test the extraction functions directly
# ---------------------------------------------------------------------------


class TestParseSkillHardProhibitions:
    """Verify SKILL.md Hard prohibitions section is parsed correctly."""

    def test_skill_section_extracted(self) -> None:
        """Script can extract the Hard prohibitions section from SKILL.md."""
        from check_global_rule_subset import parse_skill_prohibitions

        items = parse_skill_prohibitions(SKILL_MD)
        # SKILL.md has 5 hard prohibitions
        assert len(items) == 5, (
            f"expected 5 SKILL prohibitions, got {len(items)}: "
            f"{[i.get('number') for i in items]}"
        )

    def test_skill_items_have_required_fields(self) -> None:
        """Each parsed item has number, title_keywords, and body."""
        from check_global_rule_subset import parse_skill_prohibitions

        items = parse_skill_prohibitions(SKILL_MD)
        for item in items:
            assert "number" in item, f"item missing 'number': {item}"
            assert "title_keywords" in item, f"item missing 'title_keywords': {item}"
            assert "body" in item, f"item missing 'body': {item}"
            assert isinstance(item["title_keywords"], set), (
                f"title_keywords must be set: {item}"
            )
            assert len(item["body"]) > 0, f"item has empty body: {item}"

    def test_skill_vm_only_item_detected(self) -> None:
        """SKILL item #5 (VM-ONLY) is detected as VM-related."""
        from check_global_rule_subset import parse_skill_prohibitions

        items = parse_skill_prohibitions(SKILL_MD)
        vm_items = [i for i in items if i.get("is_vm_only")]
        assert len(vm_items) >= 1, "expected at least 1 VM-ONLY item in SKILL.md"


class TestParseGlobalRuleHardProhibitions:
    """Verify global-rule section 7 is parsed correctly."""

    def test_global_rule_section_extracted(self) -> None:
        """Script can extract section 7 from the global rule file."""
        from check_global_rule_subset import parse_global_rule_prohibitions

        items = parse_global_rule_prohibitions(GLOBAL_RULE)
        # Global rule currently has 3 hard prohibitions
        assert len(items) >= 1, (
            f"expected >= 1 global rule prohibition, got {len(items)}"
        )

    def test_global_rule_items_have_required_fields(self) -> None:
        """Each parsed item has number, title_keywords, and body."""
        from check_global_rule_subset import parse_global_rule_prohibitions

        items = parse_global_rule_prohibitions(GLOBAL_RULE)
        for item in items:
            assert "number" in item
            assert "title_keywords" in item
            assert "body" in item


class TestBidirectionalCheck:
    """Verify the bidirectional subset relationship detection."""

    def test_bidirectional_fully_covered(self) -> None:
        """After fix: global rules + behaviors cover all SKILL items in both
        hard prohibitions and behaviors sections."""
        from check_global_rule_subset import (
            check_bidirectional,
            parse_global_rule_behaviors,
            parse_global_rule_prohibitions,
            parse_skill_behaviors,
            parse_skill_prohibitions,
        )

        skill_items = parse_skill_prohibitions(SKILL_MD) + parse_skill_behaviors(SKILL_MD)
        global_items = (
            parse_global_rule_prohibitions(GLOBAL_RULE)
            + parse_global_rule_behaviors(GLOBAL_RULE)
        )
        forward_missing, reverse_missing = check_bidirectional(global_items, skill_items)
        assert len(forward_missing) == 0, (
            f"expected 0 forward missing, got {len(forward_missing)}: "
            f"{[(i['number'], i.get('title_raw', '')) for i in forward_missing]}"
        )
        assert len(reverse_missing) == 0, (
            f"expected 0 reverse missing, got {len(reverse_missing)}: "
            f"{[(i['number'], i.get('title_raw', '')) for i in reverse_missing]}"
        )

    def test_forward_check_returns_empty_when_covered(self) -> None:
        """When all global-rule items are covered by SKILL items,
        forward_missing is empty."""
        from check_global_rule_subset import check_bidirectional

        skill_items = [
            {
                "number": 1,
                "title_keywords": {"no", "mid-iteration", "questioning"},
                "body": "No mid-iteration questioning. Decide and continue.",
                "is_vm_only": False,
            },
            {
                "number": 2,
                "title_keywords": {"no", "cascade", "abort"},
                "body": "No cascade abort. Failure on claim C becomes deferred.",
                "is_vm_only": False,
            },
        ]
        global_items = [
            {
                "number": 1,
                "title_keywords": {"no", "mid-iteration", "questioning"},
                "body": "Do not ask user mid-iteration",
            },
            {
                "number": 2,
                "title_keywords": {"no", "cascade", "abort"},
                "body": "Do not cascade abort",
            },
        ]
        forward_missing, reverse_missing = check_bidirectional(global_items, skill_items)
        assert len(forward_missing) == 0, (
            f"expected 0 forward missing, got {len(forward_missing)}: {forward_missing}"
        )

    def test_reverse_check_detects_uncovered_skill_item(self) -> None:
        """When a SKILL item has no matching global-rule item,
        it appears in reverse_missing."""
        from check_global_rule_subset import check_bidirectional

        skill_items = [
            {
                "number": 1,
                "title_keywords": {"no", "questioning"},
                "body": "No questioning",
                "is_vm_only": False,
            },
            {
                "number": 2,
                "title_keywords": {"vm-only", "host", "forbidden"},
                "body": "VM-ONLY dynamic tools forbidden on host",
            },
        ]
        global_items = [
            {
                "number": 1,
                "title_keywords": {"no", "questioning"},
                "body": "Do not question",
            },
        ]
        forward_missing, reverse_missing = check_bidirectional(global_items, skill_items)
        assert len(reverse_missing) == 1
        assert reverse_missing[0]["number"] == 2

    def test_both_directions_pass_when_identical(self) -> None:
        """When both files have the same items, both directions pass."""
        from check_global_rule_subset import check_bidirectional

        shared_items = [
            {
                "number": 1,
                "title_keywords": {"no", "questioning"},
                "body": "No questioning during iteration",
                "is_vm_only": False,
            },
            {
                "number": 2,
                "title_keywords": {"vm-only", "forbidden", "host"},
                "body": "VM-ONLY tools forbidden on host. mcp__x64dbg__start_session forbidden.",
            },
        ]
        forward_missing, reverse_missing = check_bidirectional(shared_items, shared_items)
        assert len(forward_missing) == 0
        assert len(reverse_missing) == 0


class TestCliInterface:
    """Verify the CLI exit codes and output format."""

    def test_exit_code_0_when_fully_covered(self) -> None:
        """Script exits 0 when there are no coverage gaps."""
        rc, stdout, stderr = _run_check()
        assert rc == 0, (
            f"expected exit code 0 (fully covered), got {rc}; "
            f"stdout={stdout!r}; stderr={stderr!r}"
        )

    def test_stdout_prints_pass_when_covered(self) -> None:
        """When fully covered, stdout contains 'PASS'."""
        rc, stdout, stderr = _run_check()
        assert "PASS" in stdout, (
            f"expected 'PASS' in stdout, got: {stdout!r}"
        )

    def test_stdout_shows_no_gaps_when_covered(self) -> None:
        """When fully covered, stdout does not contain 'MISSING_FROM_GLOBAL'."""
        rc, stdout, stderr = _run_check()
        assert "MISSING_FROM_GLOBAL" not in stdout and "EXTRA_IN_GLOBAL" not in stdout, (
            f"expected no gap markers in stdout, got: {stdout!r}"
        )

    def test_with_synthetic_covered_fixture(self, tmp_path: Path) -> None:
        """When both directions are fully covered, script exits 0."""
        # Create a synthetic global-rule file that covers all SKILL items
        # (both hard prohibitions and behaviors sections)
        synthetic_global = tmp_path / "global-rule-synth.md"
        synthetic_global.write_text(
            "## 4. 5 behaviors\n\n"
            "1. **Self-recovery.** L1 same-MCP-other-mode, L2 read skill setup.sh, "
            "L3 dispatch env-fix worker.\n"
            "2. **Specialist agents first.** ghidra-light, cti-correlator, "
            "floss-filter, pefile-signature, verdict-scorer.\n"
            "3. **Cost is informational.** Cost warnings are noise, never a stop "
            "reason.\n"
            "4. **Poll every worker.** cat worker-status files every turn.\n"
            "5. **The false-completion trap.** Open-claim count is the truth.\n"
            "\n## 7. Hard prohibitions\n\n"
            "1. **No mid-iteration questioning.** Do not ask user mid-iteration.\n"
            "2. **No cascade abort.** Single claim failure does not cascade.\n"
            "3. **User feedback dual-layer.** Accept user feedback as hypothesis.\n"
            "4. **Re-plan only on.** Re-plan only on verified finding, "
            "refutation, or task_spec update.\n"
            "5. **VM-ONLY dynamic tools.** x64dbg and Frida are VM-resident. "
            "Forbidden: mcp__x64dbg__start_session, mcp__frida__spawn.\n"
            "\n## 8. Other section\n",
            encoding="utf-8",
        )
        rc, stdout, stderr = _run_check(skill_md=SKILL_MD, global_rule=synthetic_global)
        assert rc == 0, (
            f"expected exit code 0 (fully covered), got {rc}; "
            f"stdout={stdout!r}; stderr={stderr!r}"
        )

    def test_with_synthetic_uncovered_fixture(self, tmp_path: Path) -> None:
        """When global-rule is missing SKILL items, script exits 1."""
        synthetic_global = tmp_path / "global-rule-synth.md"
        synthetic_global.write_text(
            "## 7. Hard prohibitions\n\n"
            "1. **No mid-iteration questioning.** Do not ask user.\n"
            "2. **Brand new invented rule.** Never eat bananas during analysis.\n"
            "\n## 8. Other section\n",
            encoding="utf-8",
        )
        rc, stdout, stderr = _run_check(skill_md=SKILL_MD, global_rule=synthetic_global)
        assert rc == 1, (
            f"expected exit code 1 (gaps), got {rc}; "
            f"stdout={stdout!r}; stderr={stderr!r}"
        )


class TestHostForbiddenToolsExtraction:
    """Verify HOST_FORBIDDEN_TOOLS are extracted from VM-ONLY items."""

    def test_skill_vm_item_contains_forbidden_tools(self) -> None:
        """SKILL VM-ONLY item references at least some HOST_FORBIDDEN_TOOLS."""
        from check_global_rule_subset import parse_skill_prohibitions

        items = parse_skill_prohibitions(SKILL_MD)
        vm_items = [i for i in items if i.get("is_vm_only")]
        assert len(vm_items) >= 1
        vm_body = " ".join(i["body"] for i in vm_items)
        assert "x64dbg" in vm_body.lower() or "mcp__" in vm_body, (
            f"VM-ONLY item body does not mention forbidden tools: {vm_body[:200]}"
        )


class TestNoHardcodedMissingItems:
    """Red line: the script must NOT hardcode specific missing items."""

    def test_script_does_not_hardcode_expected_missing(self) -> None:
        """The check script does not hardcode expected missing items."""
        source = SCRIPT.read_text(encoding="utf-8") if SCRIPT.exists() else ""
        # The script should not have a variable called expected_missing
        assert "expected_missing" not in source, (
            "script must not hardcode expected missing items"
        )

    def test_script_does_not_hardcount_missing(self) -> None:
        """The check script does not assert a specific missing count."""
        source = SCRIPT.read_text(encoding="utf-8") if SCRIPT.exists() else ""
        # Should not contain patterns like "len(missing) == 2" or ">= 2"
        assert "len(missing) ==" not in source, (
            "script must not hardcode expected missing count"
        )
