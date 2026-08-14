# -*- coding: utf-8 -*-
"""tests/test_cli_matrix.py — 9 独立 CLI 收敛 (issue #5, plan §8; #316 +mcp_probe)。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"

CLIS = [
    "kunglao.py",
    "kunglao-decide.py",
    "kunglao-verify.py",
    "kunglao-record.py",
    "kunglao-monitor.py",
    "kunglao-init.py",
    "kunglao-eval.py",
    "kunglao-digest.py",
    "mcp_probe.py",  # #316: MCP supply probe (manifest clis 第 9 项)
]


def test_all_clis_exist():
    for cli in CLIS:
        assert (SCRIPTS / cli).exists(), f"缺 CLI: {cli}"


def test_all_clis_help_exit_zero():
    for cli in CLIS:
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / cli), "--help"],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0, f"{cli} --help exit {r.returncode}\nstderr={r.stderr[:300]}"


def test_no_kong_named_cli_remains():
    leftover = [p.name for p in SCRIPTS.glob("kong-*.py") if "kong-refactor" not in p.name]
    legacy = [n for n in leftover if n != "kong.py"]
    assert not legacy, f"残留 kong-* CLI (应已 rename): {legacy}"
