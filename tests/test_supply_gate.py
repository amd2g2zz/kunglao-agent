# -*- coding: utf-8 -*-
"""tests/test_supply_gate.py — issue #767: every DECLARED face must resolve.

The supply gate (devkit/supply_gate.py) parses the three declared-face
families and FAILS (non-zero) on any face that does not resolve to an
in-tree artifact or a pinned installable source:

  1. plugin-mcp  — .claude-plugin/plugin.json mcpServers commands
  2. agents      — agents/*.md frontmatter tool entries (Bash paths,
                   mcp__server__* references)
  3. env-table   — scripts/mcp_probe.py MANIFEST rows (the MCP env table):
                   carriage claims must follow a face that resolves; any
                   git+ URL cited must carry a non-branch pin.

Demonstration pins (the #767 defect class): the gate is RED on a fixture
declaring the old vapor face (`python -m camoufox_reverse_mcp` — module
in no public index, not in tree) and GREEN after the #767 ruling change
(uv against git+URL@v1.1.1).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "devkit"))

import supply_gate  # noqa: E402

CAMOUFOX_PIN = ("git+https://github.com/WhiteNightShadow/"
                "camoufox-reverse-mcp.git@v1.1.1")

OLD_VAPOR_FACE = {"command": "python",
                  "args": ["-m", "camoufox_reverse_mcp"]}
NEW_PINNED_FACE = {"command": "uv",
                   "args": ["run", "--no-project", "--with", CAMOUFOX_PIN,
                            "python", "-m", "camoufox_reverse_mcp"]}


def make_fixture(tmp_path: Path, face: dict) -> Path:
    """Minimal plugin root: a .claude-plugin/plugin.json + empty agents/."""
    root = tmp_path / "pluginroot"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / "agents").mkdir()
    (root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "fixture", "mcpServers": {"camoufox-reverse":
                                                      face}}),
        encoding="utf-8")
    return root


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "devkit" / "supply_gate.py"), *args],
        capture_output=True, text=True, timeout=120, cwd=str(REPO_ROOT),
        encoding="utf-8", errors="replace",
    )


# ---------- 1. the #767 demonstration pins ----------

def test_old_vapor_face_is_red(tmp_path):
    root = make_fixture(tmp_path, OLD_VAPOR_FACE)
    violations = supply_gate.violations(root)
    cam = [v for v in violations if v["name"] == "camoufox-reverse"]
    assert cam, f"the vapor face must be flagged: {violations}"
    assert "vapor" in cam[0]["reason"] or "unresolved" in cam[0]["reason"]
    r = run_cli("--root", str(root))
    assert r.returncode == 1, r.stdout + r.stderr


def test_pinned_git_face_is_green(tmp_path):
    root = make_fixture(tmp_path, NEW_PINNED_FACE)
    assert supply_gate.violations(root) == []
    r = run_cli("--root", str(root))
    assert r.returncode == 0, r.stdout + r.stderr


def test_unpinned_git_ref_is_red(tmp_path):
    root = make_fixture(tmp_path, {
        "command": "uv",
        "args": ["run", "--no-project", "--with",
                 "git+https://github.com/WhiteNightShadow/"
                 "camoufox-reverse-mcp.git@main",
                 "python", "-m", "camoufox_reverse_mcp"]})
    violations = supply_gate.violations(root)
    assert violations, "a branch ref is not a pin"
    assert "pin" in violations[0]["reason"]


def test_in_tree_script_face_is_green(tmp_path):
    root = make_fixture(tmp_path, OLD_VAPOR_FACE)
    # swap the face set for an in-tree artifact command (keeping the
    # camoufox carriage the env-table family pins) + create the artifact
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps(
        {"mcpServers": {
            "camoufox-reverse": NEW_PINNED_FACE,
            "local-server": {"command": "uv", "args": [
                "run", "python", "scripts/local_srv.py"]}}}),
        encoding="utf-8")
    (root / "scripts").mkdir()
    (root / "scripts" / "local_srv.py").write_text("pass\n", encoding="utf-8")
    assert supply_gate.violations(root) == []


def test_unknown_command_face_is_red(tmp_path):
    root = make_fixture(tmp_path, {"command": "definitely-not-a-tool",
                                   "args": []})
    assert supply_gate.violations(root)


# ---------- 2. agents faces ----------

def test_agent_bash_face_missing_file_is_red(tmp_path):
    root = make_fixture(tmp_path, NEW_PINNED_FACE)
    (root / "agents" / "w.md").write_text(
        "---\nname: w\nallowedTools:\n"
        "- Bash(python scripts/missing_tool.py:*)\n---\nbody\n",
        encoding="utf-8")
    violations = supply_gate.violations(root)
    assert any(v["family"] == "agents" for v in violations), violations


def test_agent_bash_face_existing_file_is_green(tmp_path):
    root = make_fixture(tmp_path, NEW_PINNED_FACE)
    (root / "scripts").mkdir()
    (root / "scripts" / "wait_tool.py").write_text("pass\n", encoding="utf-8")
    (root / "agents" / "w.md").write_text(
        "---\nname: w\nallowedTools:\n"
        "- Bash(python scripts/wait_tool.py:*)\n---\nbody\n",
        encoding="utf-8")
    assert supply_gate.violations(root) == []


def test_agent_mcp_permission_refs_are_not_launch_faces(tmp_path):
    """`mcp__server__*` entries in agent frontmatter are harness permission
    grants, not launch commands — supply for the underlying server is
    gated by the plugin-mcp and env-table families, so the gate neither
    flags nor blesses them here."""
    root = make_fixture(tmp_path, NEW_PINNED_FACE)
    (root / "agents" / "w.md").write_text(
        "---\nname: w\nallowedTools:\n- mcp__camoufox-reverse__*\n"
        "disallowedTools:\n- mcp__no-such-server__*\n---\nbody\n",
        encoding="utf-8")
    assert supply_gate.violations(root) == []


def test_agent_parameterized_placeholders_are_not_faces(tmp_path):
    """`<skill_root>` / `tools-local/<name>.py` are templates, not
    concrete faces — the gate must not flag them."""
    root = make_fixture(tmp_path, NEW_PINNED_FACE)
    (root / "agents" / "w.md").write_text(
        "---\nname: w\nallowedTools:\n"
        "- Bash(python <skill_root>/scripts/recall.py:*)\n---\nbody\n",
        encoding="utf-8")
    assert supply_gate.violations(root) == []


# ---------- 3. env-table rows (mcp_probe MANIFEST) ----------

def test_env_carried_claim_follows_the_plugin_face(tmp_path):
    """The camoufox MANIFEST row claims plugin carriage — the claim is only
    as good as the plugin face behind it (the #767 defect class)."""
    red_root = make_fixture(tmp_path / "red", OLD_VAPOR_FACE)
    assert any(v["family"] == "env-table" for v in
               supply_gate.violations(red_root))
    green_root = make_fixture(tmp_path / "green", NEW_PINNED_FACE)
    env_violations = [v for v in supply_gate.violations(green_root)
                      if v["family"] == "env-table"]
    assert env_violations == []


def test_env_row_git_urls_carry_pins(tmp_path):
    root = make_fixture(tmp_path, NEW_PINNED_FACE)
    assert supply_gate.violations(root) == []


# ---------- 4. the real repo (post-ruling regression pin) ----------

def test_real_repo_all_faces_resolve():
    assert supply_gate.violations(REPO_ROOT) == []


def test_cli_json_contract():
    r = run_cli("--json")
    assert r.returncode == 0, r.stdout + r.stderr
    doc = json.loads(r.stdout)
    assert doc["violations"] == []
    assert isinstance(doc["faces"], list) and doc["faces"]
    r2 = run_cli()
    assert r2.returncode == 0


def test_cli_usage_error_exit2():
    r = run_cli("--root")
    assert r.returncode == 2
