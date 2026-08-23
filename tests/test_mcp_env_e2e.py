#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_mcp_env_e2e.py — issue #515 acceptance 3: mock-mcp-face
artifact→evidence e2e (one CI-reproducible chain).

fake claude-json (camoufox / gitnexus / playwright — the issue-trigger
scenario class)
  → scripts/mcp_probe.py --mcp-inventory        (probe; artifact lands in <ws>/evidence/)
  → tools/ext-scan.py --with-mcp <probe.json>   (ext index generation, sandbox root)
  → tools/tool-search.py --find <kw>            (discovery hit: name + claude-json source)
  → devkit/subagent_review tools_used resolution (mcp entry citable → Gate 5 face)

Every hop is a REAL subprocess (CLI boundary, exit codes, stdout) — no
organ internals are mocked. The mock mcp face is a JSON config file: the
probe only READS it (zero network, zero spawn, zero execution — the
describe-only contract is structural, not procedural).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "devkit"))

MCP_PROBE = REPO_ROOT / "scripts" / "mcp_probe.py"
EXT_SCAN = REPO_ROOT / "tools" / "ext-scan.py"
TOOL_SEARCH = REPO_ROOT / "tools" / "tool-search.py"

import subagent_review as sr  # noqa: E402

FAKE_CLAUDE_JSON = {
    "mcpServers": {
        "camoufox": {
            "type": "stdio", "command": "uvx", "args": ["camoufox-mcp"],
            "env": {"CAMOUFOX_API_KEY": "sk-e2e-do-not-leak"},
        },
        "gitnexus": {"type": "stdio", "command": "gitnexus",
                     "args": ["mcp"]},
    },
    "projects": {},
}

CLI_FIXTURE = '''#!/usr/bin/env python3
"""alpha_tool.py - fixture CLI."""
if __name__ == "__main__":
    raise SystemExit(0)
'''


def run_py(script: Path, *args: str) -> subprocess.CompletedProcess:
    # UTF-8 decode: the probed CLIs carry the #317 UTF-8 stdout guard.
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, timeout=120, cwd=str(REPO_ROOT),
        encoding="utf-8", errors="replace",
    )


@pytest.fixture
def mock_env(tmp_path: Path) -> dict:
    """The mock mcp face + the sandbox repo root consuming it."""
    ws = tmp_path / "ws"
    ws.mkdir()
    claude_json = tmp_path / "fake-claude.json"
    claude_json.write_text(json.dumps(FAKE_CLAUDE_JSON), encoding="utf-8")
    # third registration surface: playwright lives in the workspace .mcp.json
    (ws / ".mcp.json").write_text(
        json.dumps({"mcpServers": {
            "playwright": {"type": "stdio", "command": "npx",
                           "args": ["@playwright/mcp"]}}}),
        encoding="utf-8")

    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "hooks").mkdir()
    (root / "references" / "re-library").mkdir(parents=True)
    (root / "tools").mkdir()
    (root / "scripts" / "alpha_tool.py").write_text(CLI_FIXTURE,
                                                    encoding="utf-8")
    # tool-search requires the INTERNAL index to exist next to the ext one
    (root / "tools" / "_INDEX.yaml").write_text(
        "schema: tools-index/1\ntools: []\n", encoding="utf-8")
    return {"ws": ws, "claude_json": claude_json, "root": root}


def test_mock_mcp_face_artifact_to_evidence_e2e(mock_env: dict) -> None:
    """The one-chain test (#515 acceptance 3): config → probe artifact in
    evidence/ → ext index → --find hit → Gate 5 tools_used resolution."""
    ws, claude_json, root = (mock_env["ws"], mock_env["claude_json"],
                             mock_env["root"])

    # -- 1. probe: enumerate the mock face, artifact lands in evidence/ --
    r = run_py(MCP_PROBE, str(ws), "--mcp-inventory",
               "--claude-json", str(claude_json))
    assert r.returncode == 0, r.stderr
    inv = json.loads(r.stdout)
    names = {s["name"] for s in inv["servers"]}
    assert names == {"camoufox", "gitnexus", "playwright"}, (
        "the three mock servers must enumerate (global + workspace surfaces)")
    assert "sk-e2e-do-not-leak" not in r.stdout, "secret hygiene on the e2e face"
    evidence = ws / "evidence"
    evidence.mkdir()
    probe_artifact = evidence / "mcp-inventory.json"
    probe_artifact.write_text(r.stdout, encoding="utf-8")

    # -- 2. generate: ext index from the probe artifact --
    r = run_py(EXT_SCAN, "--root", str(root), "--with-mcp",
               str(probe_artifact))
    assert r.returncode == 0, r.stderr
    ext_path = root / "tools" / "_INDEX.ext.yaml"
    assert ext_path.is_file()

    # -- 3. discover: --find hits the mcp entries with their provenance --
    r = run_py(TOOL_SEARCH, "--find", "camoufox", str(root / "tools" / "_INDEX.yaml"))
    assert r.returncode == 0, r.stderr
    assert "mcp__camoufox" in r.stdout, (
        f"--find must surface the mcp entry, got: {r.stdout!r}")
    assert "claude-json" in r.stdout
    r = run_py(TOOL_SEARCH, "--find", "playwright", "--json",
               str(root / "tools" / "_INDEX.yaml"))
    assert r.returncode == 0, r.stderr
    hits = json.loads(r.stdout)["tools"]
    mcp_hits = [h for h in hits if h.get("kind") == "mcp"]
    assert any(h["name"] == "mcp__playwright" for h in mcp_hits), (
        f"mcp kind projection missing: {hits}")
    # repo face still discoverable alongside the environment face
    r = run_py(TOOL_SEARCH, "--find", "alpha", "--json",
               str(root / "tools" / "_INDEX.yaml"))
    assert r.returncode == 0, r.stderr
    assert any(h["name"] == "alpha_tool"
               for h in json.loads(r.stdout)["tools"])

    # -- 4. cite: tools_used mcp entry resolves (Gate 5 surface) --
    assert sr._tool_resolves("mcp__camoufox", root)
    assert sr._tool_resolves("mcp__gitnexus", root)
    assert sr._tool_resolves("mcp__playwright", root)

    # -- 5. Gate 5 face: a review citing mcp entries validates --
    review = {
        "agent": "kunglao-worker",
        "plan": "use the camoufox mcp face for the stealth-browse claim",
        "status_sync": "runs/worker-status-mock-mcp.md",
        "tools_used": ["mcp__camoufox", "mcp__playwright"],
        "verified_by": "pending-515-reviewer",
    }
    rev_dir = root / ".subagent-review"
    rev_dir.mkdir()
    rev_path = rev_dir / "2026-08-20-515-mock-mcp.json"
    rev_path.write_text(json.dumps(review), encoding="utf-8")
    saved_root = sr.REPO_ROOT
    sr.REPO_ROOT = root
    try:
        ok, msg = sr._validate_one(rev_path)
    finally:
        sr.REPO_ROOT = saved_root
    assert ok, msg


def test_unregistered_mcp_citation_fails_gate5_resolution(
        mock_env: dict) -> None:
    """Negative control on the same face: an mcp__ name NOT in the
    generated index resolves nowhere — self-invention signal stands."""
    root = mock_env["root"]
    assert not sr._tool_resolves("mcp__ghost", root), (
        "an unindexed mcp name must not resolve (bare-name resolution "
        "stays grounded in the generated catalog)")
