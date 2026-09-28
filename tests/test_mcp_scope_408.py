# -*- coding: utf-8 -*-
"""Tests for #408 — MCP registration scope redesign (deploy-truth batch).

RED-first contract (TDD):

1. Plugin-carried MCPs: `.claude-plugin/plugin.json` declares `mcpServers`
   with camoufox-reverse (stdio: `python -m camoufox_reverse_mcp`) — zero
   registration in any workspace; the server ships with the plugin.
2. The probe (scripts/mcp_probe.py) reads workspace `.mcp.json` +
   plugin-carried servers ONLY. The `~/.claude.json` probe path is DELETED
   (no-backcompat policy): no probe face may open any `*.claude.json` path,
   pinned here with a poisoned loader.
3. Approval state (#408 CRITICAL refinement): project-scope servers persist
   as "pending approval" forever when the approval flag lives in a
   root-owned ~/.claude.json. Sudo-free fix: `enableAllProjectMcpServers:
   true` merged non-destructively into the WORKSPACE `.claude/settings.json`;
   env_check's MCP face verifies it (pending-forever = FAIL naming the
   remediation).
4. The workspace .mcp.json scaffold doctrine matches: it names the approval
   flag, never instructs a user-level `claude mcp add` for the
   plugin-carried server.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS))

import mcp_probe  # noqa: E402


# ---------- helpers ----------

def _make_ws(tmp_path: Path, project_type: str | None = None) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    if project_type:
        (ws / "analysis_state.txt").write_text(
            f"# analysis_state\nproject_type={project_type}\n", encoding="utf-8")
    return ws


def _poison_claude_json(tmp_path: Path) -> Path:
    """A canary file: if ANY probe face reads it, the no-read pin fires."""
    p = tmp_path / "poison.claude.json"
    p.write_text(json.dumps({"mcpServers": {"x64dbg": {"command": "poison"}}}),
                 encoding="utf-8")
    return p


@pytest.fixture
def no_user_global_read(monkeypatch):
    """Pin: no probe face ever loads a `*.claude.json` path (#408).

    Monkeypatches mcp_probe._load_json (the single read primitive) to record
    every path and raise on any claude.json-shaped name."""
    reads: list[str] = []
    real = mcp_probe._load_json

    def spy(path):
        s = str(path)
        reads.append(s)
        if ".claude.json" in s or s.endswith("poison.claude.json"):
            raise AssertionError(
                f"#408 no-backcompat violation: probe face read the deleted "
                f"user-global surface: {s}")
        return real(path)

    monkeypatch.setattr(mcp_probe, "_load_json", spy)
    return reads


# ---------- 1. plugin manifest carries the server ----------

def test_plugin_manifest_declares_camoufox_reverse():
    manifest = json.loads(
        (ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    servers = manifest.get("mcpServers")
    assert isinstance(servers, dict) and servers, (
        "plugin.json must declare an inline mcpServers map (#408)")
    entry = servers.get("camoufox-reverse")
    assert isinstance(entry, dict), "camoufox-reverse must ship with the plugin"
    assert entry.get("command") == "python"
    assert entry.get("args") == ["-m", "camoufox_reverse_mcp"], (
        "documented invocation: python -m camoufox_reverse_mcp")


def test_plugin_declared_servers_reads_manifest():
    servers = mcp_probe.plugin_declared_servers()
    assert "camoufox-reverse" in servers
    assert servers["camoufox-reverse"]["command"] == "python"


def test_plugin_declared_servers_tolerates_path_and_array_forms(tmp_path):
    """Manifest schema: mcpServers may be an inline map, a ./-relative path,
    or an array mixing both — the reader absorbs every declared shape."""
    root = tmp_path / "plugin"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / "mcp.json").write_text(json.dumps(
        {"mcpServers": {"from-path": {"command": "x"}}}), encoding="utf-8")
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({
        "mcpServers": ["./mcp.json",
                       {"inline": {"command": "y"}}],
    }), encoding="utf-8")
    servers = mcp_probe.plugin_declared_servers(root)
    assert set(servers) == {"from-path", "inline"}


def test_plugin_declared_servers_fail_open_on_missing(tmp_path):
    assert mcp_probe.plugin_declared_servers(tmp_path) == {}


# ---------- 2. probe faces read workspace + plugin ONLY ----------

def test_registered_names_reads_workspace_and_plugin_only(
        tmp_path, monkeypatch, no_user_global_read):
    ws = _make_ws(tmp_path)
    poison = _poison_claude_json(tmp_path)
    monkeypatch.setenv("KUNGLAO_CLAUDE_JSON", str(poison))
    (ws / ".mcp.json").write_text(json.dumps(
        {"mcpServers": {"ghidra": {"command": "bridge"}}}), encoding="utf-8")
    found = mcp_probe.registered_names(None, ws)
    assert found["ghidra"] == ["workspace"]
    assert found["camoufox-reverse"] == ["plugin-carried"]
    assert "x64dbg" not in found, "the poison user-global file must be ignored"
    assert no_user_global_read, "the loader spy must have observed the reads"


def test_registered_server_urls_reads_workspace_and_plugin_only(
        tmp_path, monkeypatch, no_user_global_read):
    """Reachability face (#202/#408): urls come from the #408 surfaces only;
    a non-None claude_json argument (toolchain merge-sync shim) is never
    opened — pinned with the poisoned loader."""
    ws = _make_ws(tmp_path)
    poison = _poison_claude_json(tmp_path)
    (ws / ".mcp.json").write_text(json.dumps(
        {"mcpServers": {"ida-pro-vm": {"url": "http://127.0.0.1:13337"}}}),
        encoding="utf-8")
    urls = mcp_probe.registered_server_urls(poison, ws)
    assert urls == {"ida-pro-vm": "http://127.0.0.1:13337"}


def test_check_mcp_web_passes_via_plugin_with_no_files(tmp_path, no_user_global_read):
    """#408 acceptance: env_check/mcp passes with ~/.claude.json absent —
    web's camoufox coverage comes from the plugin carriage."""
    ws = _make_ws(tmp_path)
    checks = mcp_probe.check_mcp(ws, "web")
    cam = [c for c in checks if c.name == "camoufox-reverse"]
    assert len(cam) == 1 and cam[0].status == "PASS", (
        f"camoufox-reverse must PASS via plugin carriage, got: {cam}")
    assert "plugin-carried" in cam[0].detail


def test_check_mcp_ignores_claude_json_argument(tmp_path, no_user_global_read):
    """Merge-sync shim: the legacy `claude_json` parameter stays ACCEPTED
    (toolchain.py sweeps in another owner's stream) but is INERT — the
    deleted surface is never opened."""
    ws = _make_ws(tmp_path)
    poison = _poison_claude_json(tmp_path)
    checks = mcp_probe.check_mcp(ws, "web", claude_json=poison)
    assert all(c.name != "x64dbg" for c in checks)


def test_mcp_inventory_scopes_and_shape(tmp_path, monkeypatch, no_user_global_read):
    ws = _make_ws(tmp_path)
    (ws / ".mcp.json").write_text(json.dumps(
        {"mcpServers": {"camoufox": {"command": "x"}}}), encoding="utf-8")
    monkeypatch.setenv("KUNGLAO_CLAUDE_JSON",
                       str(_poison_claude_json(tmp_path)))
    inv = mcp_probe.mcp_inventory(ws)
    assert inv["schema"] == mcp_probe.INVENTORY_SCHEMA
    assert "claude_json" not in inv, "deleted surface must not be named"
    by_name = {s["name"]: s for s in inv["servers"]}
    assert set(by_name) == {"camoufox", "camoufox-reverse"}
    assert by_name["camoufox"]["sources"] == ["workspace"]
    assert by_name["camoufox-reverse"]["sources"] == ["plugin-carried"]


def test_cli_drops_claude_json_flag(tmp_path):
    """The --claude-json CLI face is deleted (no-backcompat)."""
    ws = _make_ws(tmp_path)
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "mcp_probe.py"), str(ws),
         "--type", "web", "--claude-json", "/tmp/x.json"],
        capture_output=True, text=True, timeout=60, encoding="utf-8")
    assert r.returncode == 2, "--claude-json must be an unknown flag now"


# ---------- 3. approval state (CRITICAL refinement) ----------

def test_ensure_project_mcp_approval_merges_non_destructively(tmp_path):
    ws = _make_ws(tmp_path)
    settings = ws / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({
        "hooks": {"PreToolUse": []},
        "statusLine": {"type": "command", "command": "render.mjs"},
    }), encoding="utf-8")
    report = mcp_probe.ensure_project_mcp_approval(ws)
    assert report["changed"] is True
    merged = json.loads(settings.read_text(encoding="utf-8"))
    assert merged["enableAllProjectMcpServers"] is True
    assert merged["hooks"] == {"PreToolUse": []}, "existing keys preserved"
    assert merged["statusLine"]["command"] == "render.mjs"


def test_ensure_project_mcp_approval_idempotent(tmp_path):
    ws = _make_ws(tmp_path)
    (ws / ".claude").mkdir(parents=True)
    settings = ws / ".claude" / "settings.json"
    settings.write_text("{}", encoding="utf-8")
    assert mcp_probe.ensure_project_mcp_approval(ws)["changed"] is True
    again = mcp_probe.ensure_project_mcp_approval(ws)
    assert again["changed"] is False, "second run must be a no-op"


def test_project_mcp_approval_reader(tmp_path):
    ws = _make_ws(tmp_path)
    assert mcp_probe.project_mcp_approval(ws) is False
    mcp_probe.ensure_project_mcp_approval(ws)
    assert mcp_probe.project_mcp_approval(ws) is True


def test_env_check_mcp_face_fails_pending_approval(tmp_path, monkeypatch):
    """#408 CRITICAL: workspace-scope servers + no approval flag = the
    pending-forever trap — FAIL naming the sudo-free remediation."""
    import env_check
    ws = _make_ws(tmp_path)
    (ws / ".mcp.json").write_text(json.dumps(
        {"mcpServers": {"camoufox-reverse": {"command": "python"}}}),
        encoding="utf-8")
    (ws / ".claude").mkdir(parents=True)
    (ws / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    status, detail = env_check.check_mcp_registered(ws, "web")
    assert status == "FAIL"
    assert "enableAllProjectMcpServers" in detail


def test_env_check_mcp_face_passes_with_approval(tmp_path, monkeypatch):
    import env_check
    ws = _make_ws(tmp_path)
    (ws / ".mcp.json").write_text(json.dumps(
        {"mcpServers": {"camoufox-reverse": {"command": "python"}}}),
        encoding="utf-8")
    mcp_probe.ensure_project_mcp_approval(ws)
    status, detail = env_check.check_mcp_registered(ws, "web")
    assert status == "PASS", detail


def test_env_check_mcp_face_plugin_only_needs_no_flag(tmp_path):
    """Plugin-carried servers are not project-scope: no workspace entries ->
    the approval flag is irrelevant to the verdict."""
    import env_check
    ws = _make_ws(tmp_path)
    status, detail = env_check.check_mcp_registered(ws, "web")
    assert status == "PASS", detail


def test_env_check_mcp_face_never_reads_user_global(
        tmp_path, monkeypatch, no_user_global_read):
    """#408 acceptance pin: the env_check MCP face reads NO ~/.claude.json —
    poisoned loader + poisoned KUNGLAO_CLAUDE_JSON must not trip."""
    import env_check
    ws = _make_ws(tmp_path)
    monkeypatch.setenv("KUNGLAO_CLAUDE_JSON",
                       str(_poison_claude_json(tmp_path)))
    status, _ = env_check.check_mcp_registered(ws, "web")
    assert status == "PASS"


# ---------- 4. scaffold doctrine ----------

def test_scaffold_comment_names_approval_not_user_level_add():
    scaffold = mcp_probe.build_scaffold_json()
    comment = scaffold["_comment"]
    assert "enableAllProjectMcpServers" in comment, (
        "scaffold must name the sudo-free approval remediation")
    assert "claude mcp add" not in comment, (
        "the user-level registration instruction is gone from the doctrine")
    assert scaffold["mcpServers"] == {}, "scaffold never shadows with placeholders"


def test_camoufox_manifest_register_text_names_plugin_carriage():
    item = next(i for i in mcp_probe.MANIFEST if i.name == "camoufox-reverse")
    assert "plugin" in item.register, (
        "remediation text must name the plugin carriage, not `claude mcp add`")
    assert "claude mcp add" not in item.register
