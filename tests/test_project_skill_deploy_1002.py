# -*- coding: utf-8 -*-
"""Issue — project-scoped skill deployment and workspace runtime root.

Owner ruling 2026-11-05: the workspace ``<ws>/.claude`` is the deployment
unit and the ONLY runtime root.  This file pins the general contract:

  1. the skill tree (root router + per-command skills + subcommands.yaml)
     is part of the deploy surface and materializes under
     ``<ws>/.claude/skills/kunglao-agent/``;
  2. a usable uv project env deploys beside it (``<ws>/.claude/pyproject.toml``)
     so ``uv run --project <ws>/.claude`` is valid;
  3. every generated hook command is rooted in the workspace — no
     ``~/.claude/plugins/cache`` / ``~/.claude/skills`` literal survives;
  4. a global skill/plugin shadow is detected and reported with
     remediation (the workspace copy is authoritative);
  5. two workspaces are isolated: deploying one never mutates the other.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

SKILL_PKG = ".claude/skills/kunglao-agent"
SKILL_REQUIRED = (
    "SKILL.md",
    "skills/kunglao-agent/SKILL.md",
    "skills/init/SKILL.md",
    "skills/analysis/SKILL.md",
    "skills/resume/SKILL.md",
    "skills/upgrade/SKILL.md",
    "skills/help/SKILL.md",
    "skills/subcommands.yaml",
)


def _toml_load(path: Path) -> dict:
    try:
        import tomli as tomllib
    except ImportError:  # Python >= 3.11
        import tomllib
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _commands(ws: Path) -> list[str]:
    settings = json.loads(
        (ws / ".claude" / "settings.json").read_text(encoding="utf-8"))
    return [h["command"]
            for face in settings.get("hooks", {}).values()
            for entry in face for h in entry.get("hooks", [])]


# ---------------------------------------------------------------------------
# 1. deploy surface
# ---------------------------------------------------------------------------

def test_manifest_deploys_the_full_skill_tree():
    import deploy_manifest as dm

    entries = {e["src"]: e for e in dm.build_entries()}
    for src in SKILL_REQUIRED:
        assert src in entries, f"skill asset missing from the deploy manifest: {src}"
        assert entries[src]["dest"].startswith(SKILL_PKG + "/"), entries[src]
    # every file under skills/ is deployed — no hand-kept subset can drift
    for p in sorted((ROOT / "skills").rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            rel = p.relative_to(ROOT).as_posix()
            assert rel in entries, f"undeployed skill file: {rel}"
    # the root router keeps its package-root name (the router's own
    # relative references keep resolving inside the deployed tree)
    assert entries["SKILL.md"]["dest"] == f"{SKILL_PKG}/SKILL.md"


def test_release_manifest_covers_the_post_466_skills():
    """The release asset list and the deploy surface agree on the skill
    tree — resume and upgrade were missing from the release list."""
    text = (ROOT / "release-manifest.yaml").read_text(encoding="utf-8")
    for rel in ("skills/resume/SKILL.md", "skills/upgrade/SKILL.md"):
        assert rel in text, f"release-manifest.yaml does not declare {rel}"


# ---------------------------------------------------------------------------
# 2. workspace env
# ---------------------------------------------------------------------------

def test_workspace_env_pyproject_matches_the_skill_dependencies(tmp_path):
    import deploy_manifest as dm

    target = dm.ensure_workspace_env(tmp_path)
    assert target == (tmp_path / ".claude" / "pyproject.toml").resolve()
    generated = _toml_load(target)
    root = _toml_load(ROOT / "pyproject.toml")
    assert generated["project"]["dependencies"] == root["project"]["dependencies"]
    assert generated["project"]["requires-python"] == root["project"]["requires-python"]
    # uv must not try to build/install a package that is not deployed
    assert generated["tool"]["uv"]["package"] is False


def test_dep_surface_gate_accepts_the_generated_workspace_env(tmp_path):
    import deploy_manifest as dm
    import dep_surface_gate as dsg

    dm.ensure_workspace_env(tmp_path)
    report = dsg.check(surface_root=ROOT, env_root=tmp_path / ".claude")
    assert report["ok"], report["missing"]


def test_deploy_workspace_copy_materializes_skill_tree_and_env(tmp_path):
    import hook_activation as ha

    ha.deploy_workspace_copy(tmp_path)
    pkg = tmp_path / ".claude" / "skills" / "kunglao-agent"
    assert (pkg / "SKILL.md").is_file()
    assert (pkg / "skills" / "resume" / "SKILL.md").is_file()
    # the router's own relative layout is preserved: skills/subcommands.yaml
    assert (pkg / "skills" / "subcommands.yaml").is_file()
    assert (tmp_path / ".claude" / "pyproject.toml").is_file()
    carrier = json.loads(
        (tmp_path / ".claude" / "deployed-manifest.json").read_text(encoding="utf-8"))
    assert f"{SKILL_PKG}/SKILL.md" in carrier["dests"]
    assert f"{SKILL_PKG}/skills/upgrade/SKILL.md" in carrier["dests"]


# ---------------------------------------------------------------------------
# 3. generated commands are workspace-rooted
# ---------------------------------------------------------------------------

def test_generated_hook_commands_are_workspace_rooted(tmp_path):
    import hook_activation as ha

    ha.deploy_workspace_copy(tmp_path)
    ha.register_hooks(workspace=tmp_path)      # raises on a selfcheck mismatch
    cmds = _commands(tmp_path)
    assert cmds, "registration must produce commands"

    env_root = (tmp_path / ".claude").resolve().as_posix()
    hooks_dir = (tmp_path / ".claude" / "hooks").resolve().as_posix()
    for c in cmds:
        assert f"uv run --project {env_root} python {hooks_dir}/" in c, (
            f"hook command is not workspace-rooted: {c}")
        assert "/.claude/plugins/cache/" not in c, f"global plugin cache leaked: {c}"
        assert "/.claude/skills/" not in c, f"global skill path leaked: {c}"


def test_scheduled_task_prompt_is_workspace_rooted(tmp_path):
    """The durable cron body is a runtime carrier too: in a
    deployed workspace it must resolve the workspace scripts under the
    workspace env, never the global install."""
    import heartbeat_loop_prompt as hlp

    ws = tmp_path
    scripts = ws / ".claude" / "scripts"
    scripts.mkdir(parents=True)
    for name in ("hook_activation.py", "heartbeat_tick.py",
                 "convergence_check.py", "heartbeat_loop_prompt.py"):
        (scripts / name).write_text("# deployed\n", encoding="utf-8")
    (ws / ".claude" / "pyproject.toml").write_text(
        "[project]\nname = \"x\"\nversion = \"0.0.0\"\n", encoding="utf-8")

    prompt = hlp.build_prompt(str(ws))
    env_root = (ws / ".claude").resolve().as_posix()
    scripts_root = (ws / ".claude" / "scripts").resolve().as_posix()
    assert f"uv run --project {env_root} python {scripts_root}/heartbeat_tick.py" in prompt
    assert f"uv run --project {env_root} python {scripts_root}/hook_activation.py" in prompt
    assert "plugins/cache" not in prompt
    assert "/.claude/skills/" not in prompt


def test_deep_install_refs_map_to_the_runtime_surface(tmp_path):
    """HIGH-1: a deep install ref must land on the DEPLOYED surface by
    subpath — <install>/scripts/... -> <ws>/.claude/scripts/... (the skill
    package carries only SKILL.md + skills/**)."""
    import install_reference as ir

    ws = tmp_path.resolve()
    pkg = ws / ".claude" / "skills" / "kunglao-agent"
    pkg.mkdir(parents=True)
    (ws / ".claude" / "scripts").mkdir(parents=True)
    (ws / ".claude" / "scripts" / "convergence_check.py").write_text(
        "# deployed\n", encoding="utf-8")
    (pkg / "SKILL.md").write_text("---\nname: kunglao-agent\n---\n",
                                  encoding="utf-8")
    (ws / "CLAUDE.md").write_text(
        "run `~/.claude/skills/kunglao-agent/scripts/convergence_check.py .`\n"
        "alt `/opt/.claude/skills/kunglao-agent/hooks/x`\n"
        "skill at `~/.claude/skills/kunglao-agent/SKILL.md`\n",
        encoding="utf-8")

    ir.rewire_workspace(ws, pkg, base=ws, outside_only=True)
    text = (ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert f"{ws.as_posix()}/.claude/scripts/convergence_check.py" in text, text
    assert f"{ws.as_posix()}/.claude/hooks/x" in text, text
    assert f"{ws.as_posix()}/.claude/skills/kunglao-agent/SKILL.md" in text, text
    assert "~/.claude/skills" not in text
    assert "/opt/.claude/skills" not in text


def test_shadow_gate_requires_the_framework_package(tmp_path):
    """MEDIUM-1: an L4 opt-in copy alone (skills/analysis) does NOT make the
    global install a shadow — only the framework package does."""
    import install_reference as ir

    ws = tmp_path
    (ws / ".claude" / "skills" / "analysis").mkdir(parents=True)
    (ws / "CLAUDE.md").write_text(
        "see ~/.claude/skills/kunglao-agent/SKILL.md\n", encoding="utf-8")
    assert ir.scan_global_shadow(ws) == {}


def test_selfcheck_rejects_a_global_project_prefix(tmp_path):
    import hook_activation as ha
    import wire_up_settings as wus

    ha.deploy_workspace_copy(tmp_path)
    ha.register_hooks(workspace=tmp_path)
    settings = tmp_path / ".claude" / "settings.json"
    doc = json.loads(settings.read_text(encoding="utf-8"))
    # reintroduce the exact defect shape: the env project points at a
    # global install, while the script path stays local (mixed root).
    for face in doc["hooks"].values():
        for entry in face:
            for h in entry.get("hooks", []):
                h["command"] = h["command"].replace(
                    f"{tmp_path.resolve().as_posix()}/.claude",
                    "/Users/someone/.claude/plugins/cache/kunglao-agent/0.1.6-rc3")
    settings.write_text(json.dumps(doc), encoding="utf-8")

    check = ha.selfcheck_registration(
        settings, expected_files=wus.WIRE_UP_HOOK_FILES,
        workspace=tmp_path, layer="project", deployed_project=tmp_path)
    assert check["ok"] is False
    assert check["mismatches"], check


# ---------------------------------------------------------------------------
# 4. global shadow detection
# ---------------------------------------------------------------------------

def test_global_shadow_is_detected_and_reported(tmp_path):
    import hook_activation as ha
    import install_reference as ir

    ws = tmp_path
    (ws / ".claude").mkdir()
    # a shadow requires a project copy to be shadowed; without one
    # the global/durable install is the legitimate active root
    pkg = ws / ".claude" / "skills" / "kunglao-agent"
    pkg.mkdir(parents=True)
    (pkg / "SKILL.md").write_text("---\nname: kunglao-agent\n---\n",
                                  encoding="utf-8")
    global_cmd = (
        "PYTHONUTF8=1 uv run --project /Users/someone/.claude/plugins/cache/"
        "kunglao-agent/kunglao-agent/0.1.6-rc3 python /Users/someone/.claude/"
        "plugins/cache/kunglao-agent/kunglao-agent/0.1.6-rc3/hooks/dispatch_gate.py")
    (ws / ".claude" / "settings.json").write_text(json.dumps({
        "hooks": {"PreToolUse": [{"matcher": "Agent", "hooks": [
            {"type": "command", "command": global_cmd}]}]}}), encoding="utf-8")
    (ws / "CLAUDE.md").write_text(
        "See ~/.claude/skills/kunglao-agent/SKILL.md for the contract.\n",
        encoding="utf-8")

    shadow = ir.scan_global_shadow(ws)
    flat = " ".join(r for refs in shadow.values() for r in refs)
    assert "plugins/cache" in flat, shadow
    assert ".claude/skills" in flat, shadow

    report = ha.verify_install_references(ws)
    assert report["shadow"], report
    assert report["ok"] is False
    assert report["remediation"], "shadow must carry remediation text"


def test_workspace_local_skill_refs_are_not_shadows(tmp_path):
    import install_reference as ir

    ws = tmp_path
    (ws / ".claude").mkdir()
    local = (ws / ".claude" / "skills" / "kunglao-agent" / "SKILL.md")
    (ws / "CLAUDE.md").write_text(f"See {local.as_posix()} for the contract.\n",
                                  encoding="utf-8")
    assert ir.scan_global_shadow(ws) == {}


# ---------------------------------------------------------------------------
# 5. two-workspace isolation
# ---------------------------------------------------------------------------

def test_two_workspaces_stay_isolated(tmp_path):
    import hook_activation as ha

    a, b = tmp_path / "ws-a", tmp_path / "ws-b"
    for ws in (a, b):
        ha.deploy_workspace_copy(ws)
        ha.register_hooks(workspace=ws)

    snapshot = {
        "settings": (b / ".claude" / "settings.json").read_bytes(),
        "carrier": (b / ".claude" / "deployed-manifest.json").read_bytes(),
        "skill": (b / ".claude" / "skills" / "kunglao-agent" / "SKILL.md").read_bytes(),
        "env": (b / ".claude" / "pyproject.toml").read_bytes(),
    }

    # upgrading/redeploying A must not touch B's effective version or env
    ha.deploy_workspace_copy(a)
    ha.register_hooks(workspace=a)

    assert (b / ".claude" / "settings.json").read_bytes() == snapshot["settings"]
    assert (b / ".claude" / "deployed-manifest.json").read_bytes() == snapshot["carrier"]
    assert ((b / ".claude" / "skills" / "kunglao-agent" / "SKILL.md")
            .read_bytes() == snapshot["skill"])
    assert (b / ".claude" / "pyproject.toml").read_bytes() == snapshot["env"]

    # each workspace resolves its OWN root — no shared singleton
    for ws in (a, b):
        env_root = (ws / ".claude").resolve().as_posix()
        for c in _commands(ws):
            assert f"uv run --project {env_root} " in c, c
