# -*- coding: utf-8 -*-
"""Issue #478 — init deploy_env 四层闭环 (L1 hooks / L2 agents / L3 MCP
record / L4 skills + env manifest).

RED contract (dev baseline 8e85dfa, 2026-08-19): a standard init exits 0
with the full scaffold but prints
    hooks skipped — no <workspace>/.claude/settings.json (HOME settings never written)
and no .claude/ ever appears — deployment requires a file nobody creates.
Subagents are never copied (README tells the user to hand-cp), and the
.mcp.json scaffold stays empty with no per-item record anywhere.
Witness: /tmp sandbox run, RC=0, ls .claude -> No such file or directory.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

from _factories import seed_bins

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
AGENTS = ROOT / "agents"
SKILLS = ROOT / "skills"

FLAG_NAME = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"

CORE_AGENTS = ("kunglao-worker.md", "kunglao-redteam.md",
               "kunglao-init-worker.md")

RC_OK = 0
RC_ERROR = 1


def _load_init():
    name = "kunglao_init_deploy_env"
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(
            name, SCRIPTS / "kunglao-init.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


def _mk_ws(tmp_path: Path, name: str = "ws") -> Path:
    ws = tmp_path / name
    seed_bins(ws, payload=b"MZ\x90\x00" + b"\x00" * 64)
    (ws / "runs").mkdir()
    return ws


def _run_init(ws: Path, extra: list[str] | None = None) -> subprocess.CompletedProcess:
    """Hermetic CLI run: KUNGLAO_CLAUDE_JSON pinned to a fake (empty-ish)
    file so user-level MCP registrations never leak in."""
    argv = [sys.executable, str(SCRIPTS / "kunglao-init.py"), str(ws), *(extra or [])]
    argv += ["--type", "windows", "--skip-toolchain", "--host-exec-protection", "enabled",
             "--profile-root", str(ws.parent / "profile-root")]
    env = {k: v for k, v in os.environ.items()
           if k not in (FLAG_NAME, "GHIDRA_HOME", "KUNGLAO_VM_HOST")}
    env["PATH"] = str(ws.parent / "empty-bin")
    (ws.parent / "empty-bin").mkdir(exist_ok=True)
    env["PYTHONIOENCODING"] = "utf-8"
    env[FLAG_NAME] = "0"
    env["KUNGLAO_CLAUDE_JSON"] = str(ws.parent / "fake-claude.json")
    if not (ws.parent / "fake-claude.json").exists():
        (ws.parent / "fake-claude.json").write_text("{}", encoding="utf-8")
    if not any(a.startswith("--host-exec-protection") for a in argv) \
            and "--resolve" not in argv:
        # #919: non-interactive tests answer the host-exec ask explicitly.
        argv += ["--host-exec-protection", "enabled"]
    return subprocess.run(argv, capture_output=True, text=True, timeout=120,
                          env=env, errors="replace")


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ===========================================================================
# L1 hooks — absence of settings.json is not a legal skip (#478 AC1)
# ===========================================================================

def test_l1_default_init_creates_settings_and_wires_hooks(tmp_path):
    """No-flag init MUST leave <ws>/.claude/settings.json present with
    registry hook entries and NO 'hooks skipped' line (RED: today the file
    never exists and init self-reports the skip with RC 0)."""
    ws = _mk_ws(tmp_path)
    r = _run_init(ws)
    assert r.returncode == RC_OK, f"init failed: {r.stdout}{r.stderr}"
    out = r.stdout + r.stderr
    settings = ws / ".claude" / "settings.json"
    assert settings.exists(), (
        f"#478 deadlock: init exited 0 without creating {settings}: {out}")
    assert "hooks skipped" not in out, (
        f"the silent-skip line must be gone from the default path: {out}")
    data = json.loads(settings.read_text(encoding="utf-8"))
    cmds = [str(h.get("command", ""))
            for entries in (data.get("hooks") or {}).values()
            for e in entries for h in e.get("hooks", [])]
    assert cmds, "settings.json carries no hook commands"
    assert any(c.endswith("worker_budget.py") for c in cmds), (
        f"registry hooks missing from the deployed file: {cmds}")


def test_l1_no_hooks_is_the_only_legal_skip(tmp_path):
    """--no-hooks -> settings not created BY INIT and the skip message
    names the flag."""
    ws = _mk_ws(tmp_path)
    r = _run_init(ws, ["--no-hooks"])
    assert r.returncode == RC_OK, f"init failed: {r.stdout}{r.stderr}"
    out = r.stdout + r.stderr
    assert "--no-hooks" in out, (
        f"the skip reason must name the flag explicitly: {out}")
    assert not (ws / ".claude" / "settings.json").exists(), (
        "--no-hooks must not create the settings file")


def test_l1_wiring_failure_is_rc_hook_wiring(tmp_path, monkeypatch):
    """A self-check failure during the default deploy still maps to
    RC_HOOK_WIRING=7 (the #445 channel, unchanged by #478)."""
    ws = _mk_ws(tmp_path)
    monkeypatch.setenv(FLAG_NAME, "0")
    mod = _load_init()
    import hook_activation
    monkeypatch.setattr(
        hook_activation, "selfcheck_registration",
        lambda *a, **k: {"ok": False, "mismatches": ["layer: injected"]})
    rc = mod.run(ws, project_type="windows",
                 profile_root=tmp_path / "profile-root",
                 skip_toolchain=True,
                 answers={"host_exec_protection": "enabled"})
    assert rc == mod.RC_HOOK_WIRING, (
        f"default hook deploy failure must FAIL (7), got {rc}")


# ===========================================================================
# L2 subagents — core 3 land, idempotent (#478 AC2)
# ===========================================================================

def test_l2_core_agents_deployed(tmp_path):
    ws = _mk_ws(tmp_path)
    r = _run_init(ws)
    assert r.returncode == RC_OK, f"init failed: {r.stdout}{r.stderr}"
    for name in CORE_AGENTS:
        src = AGENTS / name
        dst = ws / ".claude" / "agents" / name
        assert dst.exists(), (
            f"core agent {name} not deployed to <ws>/.claude/agents/: {r.stdout}")
        assert _sha256(dst) == _sha256(src), (
            f"deployed {name} differs from repo source")


def test_l2_idempotent_rerun_hash_stable(tmp_path):
    """--assume-yes-free idempotence: rerunning init leaves the agent
    copies byte-identical (sha256 guard skips equal; no rewrite churn)."""
    ws = _mk_ws(tmp_path)
    r1 = _run_init(ws)
    assert r1.returncode == RC_OK, r1.stderr
    before = {n: _sha256(ws / ".claude" / "agents" / n) for n in CORE_AGENTS}
    r2 = _run_init(ws)
    assert r2.returncode == RC_OK, r2.stderr
    after = {n: _sha256(ws / ".claude" / "agents" / n) for n in CORE_AGENTS}
    assert before == after, "agent copies drifted across idempotent rerun"


def test_l2_no_hooks_still_deploys_agents(tmp_path):
    """--no-hooks opts out of L1 ONLY — L2 is a separate layer."""
    ws = _mk_ws(tmp_path)
    r = _run_init(ws, ["--no-hooks"])
    assert r.returncode == RC_OK, r.stderr
    assert (ws / ".claude" / "agents" / "kunglao-worker.md").exists(), (
        "--no-hooks must not disable the agents layer")


# ===========================================================================
# L3 MCP — probe + record, never execute registration (#478 AC3)
# ===========================================================================

def _manifest(ws: Path) -> dict:
    import yaml
    return yaml.safe_load((ws / "env-manifest.yaml").read_text(encoding="utf-8"))


def test_l3_unregistered_hard_recorded_manual_not_silent(tmp_path):
    """Fake claude.json with NOTHING registered: ghidra (HARD, windows)
    lands in the manifest as manual with its register command; stderr names
    the missing registration; init still exits 0 (WARN semantics)."""
    ws = _mk_ws(tmp_path)
    (ws.parent / "fake-claude.json").write_text(
        json.dumps({"mcpServers": {}, "projects": {}}), encoding="utf-8")
    r = _run_init(ws)
    assert r.returncode == RC_OK, f"init failed: {r.stdout}{r.stderr}"
    man = _manifest(ws)
    comps = {c["name"]: c for c in man["components"]}
    ghidra = comps.get("mcp:ghidra")
    assert ghidra is not None, f"mcp:ghidra missing from env manifest: {comps}"
    assert ghidra["status"] == "manual", (
        f"unregistered HARD item must record manual, got {ghidra}")
    assert "claude mcp add" in str(ghidra.get("detail", "")), (
        f"the register command must be recorded for the human: {ghidra}")
    assert "ghidra" in (r.stdout + r.stderr), (
        "stderr must name the missing MCP registration (never silent)")


def test_l3_registered_pass(tmp_path):
    """ghidra registered user-global -> manifest records pass."""
    ws = _mk_ws(tmp_path)
    (ws.parent / "fake-claude.json").write_text(
        json.dumps({"mcpServers": {"ghidra": {"command": "x"}}}), encoding="utf-8")
    r = _run_init(ws)
    assert r.returncode == RC_OK, r.stderr
    comps = {c["name"]: c for c in _manifest(ws)["components"]}
    assert comps["mcp:ghidra"]["status"] == "pass", comps["mcp:ghidra"]


def test_l3_workspace_mcp_json_seen_from_foreign_cwd(tmp_path, monkeypatch):
    """#478 review MEDIUM-1 regression: a workspace-level .mcp.json
    registration must be recorded as pass even when init runs with cwd !=
    ws (the old `Path(".")` read the process cwd instead)."""
    ws = _mk_ws(tmp_path)
    (ws / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"ghidra": {"command": "x"}}}),
        encoding="utf-8")
    foreign = tmp_path / "foreign-cwd"
    foreign.mkdir()
    monkeypatch.chdir(foreign)
    r = _run_init(ws)
    assert r.returncode == RC_OK, (
        f"init from foreign cwd failed: {r.stdout}{r.stderr}")
    comps = {c["name"]: c for c in _manifest(ws)["components"]}
    assert comps["mcp:ghidra"]["status"] == "pass", (
        f"workspace-level .mcp.json registration missed (cwd leak): "
        f"{comps.get('mcp:ghidra')}")


# ===========================================================================
# L4 skills — explicit flag only (#478 AC4)
# ===========================================================================

def test_l4_no_flag_deploys_nothing(tmp_path):
    ws = _mk_ws(tmp_path)
    r = _run_init(ws)
    assert r.returncode == RC_OK, r.stderr
    skills_dir = ws / ".claude" / "skills"
    assert not skills_dir.exists() or not any(skills_dir.iterdir()), (
        "no --skills flag must install nothing")


def test_l4_skills_flag_deploys_named_dir(tmp_path):
    ws = _mk_ws(tmp_path)
    r = _run_init(ws, ["--skills", "analysis"])
    assert r.returncode == RC_OK, (
        f"--skills analysis must deploy: {r.stdout}{r.stderr}")
    dst = ws / ".claude" / "skills" / "analysis"
    assert dst.is_dir(), "skills/analysis not deployed"
    assert (dst / "SKILL.md").exists(), "deployed skill lost SKILL.md"


def test_l4_unknown_skill_fails_fast(tmp_path):
    ws = _mk_ws(tmp_path)
    r = _run_init(ws, ["--skills", "definitely-not-a-skill"])
    assert r.returncode == RC_ERROR, (
        f"unknown --skills name must fail RC_ERROR=1: {r.stdout}{r.stderr}")
    assert "definitely-not-a-skill" in (r.stdout + r.stderr)


# ===========================================================================
# env manifest — the deployment ledger (#478 AC5)
# ===========================================================================

def test_env_manifest_written_with_ledger(tmp_path):
    ws = _mk_ws(tmp_path)
    r = _run_init(ws)
    assert r.returncode == RC_OK, r.stderr
    man = _manifest(ws)
    assert man["project_type"] == "windows"
    names = {c["name"] for c in man["components"]}
    assert "hooks" in names and f"agent:kunglao-worker" in names, names


def test_env_manifest_not_in_state_hash_resume_clean(tmp_path):
    """The manifest is a deployment ledger, NOT analysis state: a rerun
    must resume without the drift WARNING (root placement, outside facts/)."""
    ws = _mk_ws(tmp_path)
    r1 = _run_init(ws)
    assert r1.returncode == RC_OK, r1.stderr
    r2 = _run_init(ws)
    assert r2.returncode == RC_OK, r2.stderr
    assert "state drift" not in (r2.stdout + r2.stderr), (
        f"env-manifest must not trip the resume drift warning: {r2.stderr}")


# ===========================================================================
# plugin_mode seam (#364 future — behavior locked, nothing implemented)
# ===========================================================================

def test_plugin_mode_skips_l1_l2(tmp_path, monkeypatch):
    """deploy_env(plugin_mode=True) skips hooks + agents but still writes
    the manifest (the seam #364's plugin form will take)."""
    ws = _mk_ws(tmp_path)
    monkeypatch.setenv(FLAG_NAME, "0")
    mod = _load_init()
    report = mod.deploy_env(ws, project_type="windows", plugin_mode=True)
    assert not (ws / ".claude" / "settings.json").exists(), (
        "plugin_mode must skip L1 hook deployment")
    assert not (ws / ".claude" / "agents").exists(), (
        "plugin_mode must skip L2 agent deployment")
    assert (ws / "env-manifest.yaml").exists(), (
        "plugin_mode still writes the env manifest")


def test_deploy_env_writes_all_layers_by_default(tmp_path, monkeypatch):
    """Direct layer-level positive proof (library surface, mirrors the CLI
    tests above): default deploy_env covers L1+L2+manifest."""
    ws = _mk_ws(tmp_path)
    monkeypatch.setenv(FLAG_NAME, "0")
    mod = _load_init()
    mod.deploy_env(ws, project_type="windows")
    assert (ws / ".claude" / "settings.json").exists()
    assert (ws / ".claude" / "agents" / "kunglao-worker.md").exists()
    assert (ws / "env-manifest.yaml").exists()
