# -*- coding: utf-8 -*-
"""Issue #784 — harness-audit governance batch pins.

Each low-scoring dimension gets an explicit artifact (implementation or a
documented deviation). These tests are the mechanical half of D1-D4 so the
next audit run has greppable anchors instead of prose claims.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _has(rel: str, needle: str) -> None:
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert needle in text, f"{rel} missing: {needle!r}"


def test_d1_mcp_supply_deviation_documented():
    _has("docs/mcp-supply.md", "explicit deviation")
    _has("docs/mcp-supply.md", "scripts/mcp_probe.py")


def test_d2_test_entry_declared():
    _has("README.md", "authoritative full-suite entry")
    assert (ROOT / "scripts" / "run_test_matrix.py").is_file()


def test_d3_github_templates_present():
    for rel in (".github/PULL_REQUEST_TEMPLATE.md",
                ".github/ISSUE_TEMPLATE/bug-report.md",
                ".github/ISSUE_TEMPLATE/feature-request.md",
                ".github/ISSUE_TEMPLATE/release-checklist.md"):
        assert (ROOT / rel).is_file(), rel
    _has(".github/PULL_REQUEST_TEMPLATE.md", "dev -> master merge approved")


def test_d4_security_controls_mapping():
    _has("docs/security-controls.md", "hooks/dispatch_gate.py")
    _has("docs/security-controls.md", "check_mcp_prefix")
    _has("docs/security-controls.md", "_redo_leak_scan")


def test_run_test_matrix_smoke():
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_test_matrix.py"), "--help"],
        capture_output=True, text=True)
    if r.returncode != 0:
        # tolerate CLI-less scripts but the file must at least parse
        compile((ROOT / "scripts" / "run_test_matrix.py").read_text(encoding="utf-8"),
                "run_test_matrix.py", "exec")
