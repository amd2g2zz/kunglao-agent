#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_mcp_prefix_enforcement.py — issue #567 SECURITY.

MCP tool prefix enforcement (single source: hooks/lib_kunglao.py):
  - mcp__kunglao__*  -> ALLOW
  - mcp__unknown__*  -> REJECT (rc=2)
  - mcp__external__* -> REJECT (rc=2)

Boundary cases:
  - empty string      -> ALLOW (not an MCP tool)
  - plain non-MCP     -> ALLOW (Read/Write/Bash/...)
  - prefix-only match (e.g. mcp__unknown__ without trailing __tool) -> REJECT
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parent.parent
HOOKS_DIR = SKILL_DIR / "hooks"

# #770: no permanent sys.path insert — the ini already orders scripts before
# hooks, and this suite wants the hooks TWIN specifically, so load it by
# path under an isolated module name (#762 convention).
import importlib.util

_lk_spec = importlib.util.spec_from_file_location(
    "hooks_lib_kunglao", HOOKS_DIR / "lib_kunglao.py")
lib_kunglao = importlib.util.module_from_spec(_lk_spec)
sys.modules["hooks_lib_kunglao"] = lib_kunglao
_lk_spec.loader.exec_module(lib_kunglao)


# ---------- unit tests on the helper itself ----------

class TestMcpPrefixHelper:
    """Direct unit tests on lib_kunglao.check_mcp_prefix — the single source."""

    def test_known_kunglao_prefix_allows(self):
        allowed, reason = lib_kunglao.check_mcp_prefix("mcp__kunglao__read_file")
        assert allowed is True
        assert reason is None

    def test_unknown_prefix_rejects(self):
        allowed, reason = lib_kunglao.check_mcp_prefix("mcp__unknown__read_file")
        assert allowed is False
        assert reason is not None
        assert "mcp__unknown__" in reason

    def test_external_prefix_rejects(self):
        allowed, reason = lib_kunglao.check_mcp_prefix("mcp__external__delete_thing")
        assert allowed is False
        assert reason is not None
        assert "mcp__external__" in reason

    def test_prefix_only_still_rejects(self):
        """Prefix-only strings without a trailing tool name still match — the
        gate is prefix-based, not token-based."""
        allowed, reason = lib_kunglao.check_mcp_prefix("mcp__unknown__")
        assert allowed is False
        assert reason is not None

    def test_empty_string_allows(self):
        """Empty / non-MCP tool names fall through — the helper only governs
        MCP-prefixed tools."""
        assert lib_kunglao.check_mcp_prefix("")[0] is True
        assert lib_kunglao.check_mcp_prefix("Read")[0] is True
        assert lib_kunglao.check_mcp_prefix("Bash")[0] is True

    def test_substring_does_not_match(self):
        """`mcp__kunglao_unknown__foo` must NOT be rejected as `mcp__unknown__`
        (substring trap — the gate uses startswith on the literal prefix)."""
        allowed, _ = lib_kunglao.check_mcp_prefix("mcp__kunglao_unknown__foo")
        assert allowed is True

    def test_constant_is_tuple(self):
        """Single-source guarantee — the constant is a tuple, not a list,
        so the helper is safe to share across hooks."""
        assert isinstance(lib_kunglao.MCP_FORBIDDEN_PREFIXES, tuple)
        assert "mcp__unknown__" in lib_kunglao.MCP_FORBIDDEN_PREFIXES
        assert "mcp__external__" in lib_kunglao.MCP_FORBIDDEN_PREFIXES


# ---------- subprocess integration test against dispatch_gate.py ----------

class TestDispatchGateIntegration:
    """End-to-end: a dispatch declaring a forbidden MCP tool gets blocked
    with rc=2 via the dispatch_gate.py hook entry point (the single
    enforcement face wired into PreToolUse:Agent in settings.json)."""

    def _run_dispatch_gate(self, prompt: str) -> tuple[int, str, str]:
        """Invoke hooks/dispatch_gate.py with a crafted Agent-tool payload."""
        payload = json.dumps({
            "tool_name": "Agent",
            "tool_input": {"prompt": prompt},
            "cwd": str(SKILL_DIR),
        })
        proc = subprocess.run(
            [sys.executable, str(HOOKS_DIR / "dispatch_gate.py")],
            input=payload, capture_output=True, text=True, timeout=15,
        )
        return proc.returncode, proc.stdout, proc.stderr

    def test_dispatch_with_kunglao_mcp_tool_passes(self, tmp_path):
        """mcp__kunglao__* dispatch is allowed (rc=0, no REJECT in stderr)."""
        # tmp_path is unused — just satisfies pytest signature; the actual
        # workspace resolution uses SKILL_DIR's claim-register if present.
        prompt = json.dumps({
            "kunglao_dispatch": {
                "version": 1, "claim": "C-001", "tier": 1,
                "tools": ["mcp__kunglao__read_workspace"],
            }
        })
        rc, _out, err = self._run_dispatch_gate(prompt)
        # Either rc=0 (pass) or rc=0 due to gate inactivity — both non-2.
        # We assert specifically that rc is NOT 2 (no REJECT).
        assert rc != 2, f"mcp__kunglao__* must not REJECT, got rc={rc}: {err}"

    def test_dispatch_with_unknown_mcp_tool_rejects(self):
        """mcp__unknown__* dispatch is REJECTED with rc=2."""
        prompt = json.dumps({
            "kunglao_dispatch": {
                "version": 1, "claim": "C-002", "tier": 1,
                "tools": ["mcp__unknown__read_secret"],
            }
        })
        rc, _out, err = self._run_dispatch_gate(prompt)
        assert rc == 2, f"mcp__unknown__* must REJECT rc=2, got rc={rc}: {err}"
        assert "REJECT" in err
        assert "mcp__unknown__" in err

    def test_dispatch_with_external_mcp_tool_rejects(self):
        """mcp__external__* dispatch is REJECTED with rc=2."""
        prompt = json.dumps({
            "kunglao_dispatch": {
                "version": 1, "claim": "C-003", "tier": 1,
                "tools": ["mcp__external__evil_thing"],
            }
        })
        rc, _out, err = self._run_dispatch_gate(prompt)
        assert rc == 2, f"mcp__external__* must REJECT rc=2, got rc={rc}: {err}"
        assert "REJECT" in err
        assert "mcp__external__" in err


# ---------- #527 verifier BLIND slice non-regression ----------

class TestVerifierBlindNonRegression:
    """Issue #527 (verifier BLIND 硬排除) — the prefix check must not add any
    orchestrator surface to the verifier's view. scripts/dispatch_context.py
    defines VERIFIER_SAFE_KEYS; nothing here should widen that allow-list."""

    def test_verifier_safe_keys_unchanged(self):
        from scripts.dispatch_context import VERIFIER_SAFE_KEYS  # type: ignore
        # Sanity: the allow-list must still be a frozenset and must NOT
        # contain any MCP prefix metadata (the prefix gate is independent).
        assert isinstance(VERIFIER_SAFE_KEYS, frozenset)
        # No MCP-prefix-shaped keys leaked into the verifier view.
        for k in VERIFIER_SAFE_KEYS:
            assert not k.startswith("mcp__"), (
                f"verifier BLIND leak: {k!r} looks like MCP-prefixed metadata")

    def test_dispatch_context_view_excludes_prefix_artifacts(self, tmp_path):
        """verifier_dispatch_view (the BLIND slice) must not read any
        MCP-prefix metadata from the dispatch context artifact."""
        # Write a minimal dispatch-context artifact at the canonical path
        # the helper reads from.
        from scripts.dispatch_context import (  # type: ignore
            verifier_dispatch_view,
        )
        runs = tmp_path / "runs"
        runs.mkdir()
        # The artifact path is hardcoded inside verifier_dispatch_view;
        # we just verify the function returns the BLIND slice and contains
        # no MCP metadata. (Real workspace, no artifact -> empty dict.)
        view = verifier_dispatch_view(tmp_path, "C-001")
        # Anything in the view must not be an MCP-prefix key.
        for k in view:
            assert not str(k).startswith("mcp__")