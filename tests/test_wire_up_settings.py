# -*- coding: utf-8 -*-
"""wire_up_settings — issue #258 project-level hook deployment.

#258 (2026-08-12): wire_up_settings() must deploy kunglao-agent hooks to the
PROJECT-level settings.json (<workspace>/.claude/settings.json) and NEVER the
user-global ~/.claude/settings.json (the pre-#258 default bound hooks to a
worktree path that died with the worktree — 8 hooks went silent at once).
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SKILL_HOOKS = ROOT / "hooks"

# The full entry set wire_up_settings registers: 9 entries / 8 distinct hook
# files (worker_budget registered under BOTH PreToolUse(Agent) and
# PostToolUse(Agent)).
WIRE_UP_ENTRIES = 9
WIRE_UP_HOOK_FILES = {
    "env_check_gate.py", "worker_budget.py", "dispatch_gate.py",
    "recall_inject.py",
    "heartbeat_touch.py", "worker_pulse.py", "state_anchor.py",
    "completion_gate.py",
}


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """Path.home() -> tmp — the regression probe that user-global settings is
    never written (the #258 hard constraint)."""
    home = tmp_path / "fake-home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(pathlib.Path, "home", lambda: home)
    return home


def _collect_commands(settings: dict) -> list[str]:
    cmds = []
    for entries in settings.get("hooks", {}).values():
        for e in entries:
            for h in e.get("hooks", []):
                cmds.append(str(h.get("command", "")))
    return cmds


def _basenames(settings: dict) -> set[str]:
    return {c.replace("\\", "/").rsplit("/", 1)[-1] for c in _collect_commands(settings)}


def test_wire_up_writes_project_settings_with_all_hooks(tmp_path, fake_home):
    ws = tmp_path / "ws"
    ws.mkdir()
    sys.path.insert(0, str(SCRIPTS))
    from wire_up_settings import wire_up_settings
    wire_up_settings(workspace=ws)
    settings_path = ws / ".claude" / "settings.json"
    assert settings_path.exists(), "project settings.json must be created"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    cmds = _collect_commands(settings)
    assert len(cmds) == WIRE_UP_ENTRIES, f"expect {WIRE_UP_ENTRIES} hook entries (got {len(cmds)}: {cmds})"
    assert _basenames(settings) == WIRE_UP_HOOK_FILES


def test_wire_up_never_writes_global(tmp_path, fake_home):
    """#258 hard constraint: user-global settings.json must not be written."""
    ws = tmp_path / "ws"
    ws.mkdir()
    sys.path.insert(0, str(SCRIPTS))
    from wire_up_settings import wire_up_settings
    wire_up_settings(workspace=ws)
    assert not (fake_home / ".claude" / "settings.json").exists(), \
        "user-global ~/.claude/settings.json must NOT be created"


def test_wire_up_global_opt_in_writes_home(tmp_path, fake_home):
    """global_opt_in=True is the explicit escape hatch — and only it."""
    ws = tmp_path / "ws"
    ws.mkdir()
    sys.path.insert(0, str(SCRIPTS))
    from wire_up_settings import wire_up_settings
    wire_up_settings(workspace=ws, global_opt_in=True)
    assert (fake_home / ".claude" / "settings.json").exists(), \
        "global_opt_in=True must write the user-global settings"


def test_wire_up_idempotent(tmp_path, fake_home):
    ws = tmp_path / "ws"
    ws.mkdir()
    sys.path.insert(0, str(SCRIPTS))
    from wire_up_settings import wire_up_settings
    wire_up_settings(workspace=ws)
    wire_up_settings(workspace=ws)  # re-run — fixed point
    settings_path = ws / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    cmds = _collect_commands(settings)
    assert len(cmds) == WIRE_UP_ENTRIES, f"re-run must not stack entries (got {len(cmds)})"
    assert _basenames(settings) == WIRE_UP_HOOK_FILES
    assert not (fake_home / ".claude" / "settings.json").exists()


def test_wire_up_hook_paths_point_to_canonical_skill(tmp_path, fake_home):
    """Hook commands must resolve to the CANONICAL skill hooks dir
    (~/.claude/skills/kunglao-agent/hooks) — absolute, never bound to the
    worktree/workspace this script happens to run from (#228 root cause: a
    worktree-bound command dies with the worktree — 8 hooks went silent at
    once; #269 requires the canonical deployed skill path)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    sys.path.insert(0, str(SCRIPTS))
    from wire_up_settings import wire_up_settings
    wire_up_settings(workspace=ws)
    settings = json.loads((ws / ".claude" / "settings.json").read_text(encoding="utf-8"))
    canonical = (fake_home / ".claude" / "skills" / "kunglao-agent" / "hooks").as_posix()
    skill_root = (fake_home / ".claude" / "skills" / "kunglao-agent").as_posix()
    ws_posix = ws.as_posix()
    for cmd in _collect_commands(settings):
        # #389: commands are `uv run --project <skill_root> <script path>` —
        # uv replaces bare python (2.x risk); the script path stays absolute
        # inside the canonical skill hooks dir (#269).
        assert cmd.startswith(f"uv run --project {skill_root} "), \
            f"hook command must invoke uv with the canonical skill root: {cmd}"
        script_path = cmd.replace("\\", "/").split()[-1]
        assert script_path.startswith(canonical), \
            f"hook command must point into the canonical skill hooks dir: {cmd}"
        assert ws_posix not in script_path, \
            f"hook command must never be workspace/worktree-bound: {cmd}"


def test_wire_up_commands_use_uv_on_this_machine(tmp_path, fake_home):
    """#389 machine-behavior: the wired commands must run via uv (bare
    `python` here is 2.7.17 — the repro — and kills every registered hook),
    and uv must actually be resolvable on this machine."""
    assert shutil.which("uv"), "uv must be resolvable on this machine"
    ws = tmp_path / "ws"
    ws.mkdir()
    sys.path.insert(0, str(SCRIPTS))
    from wire_up_settings import wire_up_settings
    wire_up_settings(workspace=ws)
    settings = json.loads((ws / ".claude" / "settings.json").read_text(encoding="utf-8"))
    cmds = _collect_commands(settings)
    assert cmds, "wire_up must emit hook commands"
    assert all(c.startswith("uv run --project ") for c in cmds), cmds
    assert not any(c.split()[0] in ("python", "python3") for c in cmds), cmds


def test_wire_up_cwd_probe(tmp_path, fake_home, monkeypatch):
    """No workspace arg -> <cwd>/.claude/settings.json (project-level, not HOME)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.chdir(ws)
    sys.path.insert(0, str(SCRIPTS))
    from wire_up_settings import wire_up_settings
    wire_up_settings()
    settings_path = ws / ".claude" / "settings.json"
    assert settings_path.exists(), "cwd probe must create <cwd>/.claude/settings.json"
    assert not (fake_home / ".claude" / "settings.json").exists()
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert _basenames(settings) == WIRE_UP_HOOK_FILES


def test_wire_up_preserves_existing_keys(tmp_path, fake_home):
    """Idempotent merge must preserve unrelated settings + other hooks."""
    ws = tmp_path / "ws"
    ws.mkdir()
    settings_path = ws / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps({
        "env": {"KUNGLAO_VM_HOST": "192.168.20.128"},
        "statusLine": {"type": "command", "command": "echo hi"},
        "hooks": {
            "PreToolUse": [{"matcher": "Bash",
                            "hooks": [{"type": "command", "command": "python C:/other/hook.py"}]}],
        },
    }), encoding="utf-8")
    sys.path.insert(0, str(SCRIPTS))
    from wire_up_settings import wire_up_settings
    wire_up_settings(workspace=ws)
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert settings["env"]["KUNGLAO_VM_HOST"] == "192.168.20.128", "env keys preserved"
    assert settings["statusLine"]["command"] == "echo hi", "statusLine preserved"
    other = [e for e in settings["hooks"]["PreToolUse"] if e.get("matcher") == "Bash"
             and "other/hook.py" in e.get("hooks", [{}])[0].get("command", "")]
    assert other, "unrelated hook entries preserved"


# ---------------------------------------------------------------------------
# hooks_selfcheck — #258 target sync: project-level primary, global warning-only
# ---------------------------------------------------------------------------

def _write_project_settings(ws: Path, hook_files: list[str] | None = None) -> Path:
    hook_files = hook_files or ["heartbeat_touch.py", "worker_budget.py",
                                "dispatch_gate.py", "worker_pulse.py"]
    p = ws / ".claude" / "settings.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    pre = [{"matcher": "Agent", "hooks": [
        {"type": "command",
         "command": f"uv run --project {ROOT.as_posix()} {SKILL_HOOKS / hf}"}
        for hf in hook_files]},
        {"matcher": "Bash", "hooks": [
            {"type": "command",
             "command": f"uv run --project {ROOT.as_posix()} {SKILL_HOOKS / 'heartbeat_touch.py'}"}]}]
    p.write_text(json.dumps({"hooks": {"PreToolUse": pre, "PostToolUse": []}}),
                 encoding="utf-8")
    return p


def _run_selfcheck(ws: Path, monkeypatch, args: list[str] | None = None) -> int:
    # hooks_selfcheck binds USER_SETTINGS = Path.home()/... at import time;
    # pop the cached module so each run binds to the CURRENT fake_home (real
    # usage is one process per invocation, so this mirrors production).
    sys.modules.pop("hooks_selfcheck", None)
    sys.path.insert(0, str(SCRIPTS))
    import hooks_selfcheck
    monkeypatch.setattr(sys, "argv", ["hooks_selfcheck.py", *(args or [str(ws)])])
    return hooks_selfcheck.main()


def test_selfcheck_ok_project_level(tmp_path, fake_home, monkeypatch, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_project_settings(ws)
    (ws / "runs").mkdir(parents=True)
    assert _run_selfcheck(ws, monkeypatch) == 0
    report = json.loads((ws / "runs" / ".hooks-selfcheck.json").read_text(encoding="utf-8"))
    assert report["project_level"]["hooks_segment"] is True
    assert report["project_level"]["missing"] == []
    assert report["user_migration_warning"] is None
    assert "project=OK" in capsys.readouterr().out


def test_selfcheck_global_leftover_warns_only(tmp_path, fake_home, monkeypatch, capsys):
    """#258: kunglao hooks in the user-global file -> WARNING (migrate), never
    rewritten, and the project-level check still decides the exit code."""
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_project_settings(ws)
    (ws / "runs").mkdir(parents=True)
    global_settings = fake_home / ".claude" / "settings.json"
    global_body = json.dumps({
        "hooks": {"PreToolUse": [{"matcher": "Agent", "hooks": [
            {"type": "command", "command": f"python {SKILL_HOOKS / 'worker_budget.py'}"}]}]},
    })
    global_settings.write_text(global_body, encoding="utf-8")
    assert _run_selfcheck(ws, monkeypatch) == 0
    out = capsys.readouterr()
    assert "migrate" in out.err, "global leftovers must produce a migration warning"
    assert global_settings.read_text(encoding="utf-8") == global_body, \
        "global settings must never be rewritten by the selfcheck (#258)"
    report = json.loads((ws / "runs" / ".hooks-selfcheck.json").read_text(encoding="utf-8"))
    assert report["user_migration_warning"], "report must carry the migration warning"


def test_selfcheck_rebuilds_project_level(tmp_path, fake_home, monkeypatch, capsys):
    """Missing project-level hooks -> auto-rebuild via --wire-up into
    <ws>/.claude/settings.json (project-level, NOT global)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    rc = _run_selfcheck(ws, monkeypatch)
    proj = json.loads((ws / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert not (fake_home / ".claude" / "settings.json").exists(), \
        "selfcheck rebuild must never write the user-global settings (#258)"
    assert rc == 0, "after project-level rebuild the selfcheck must pass"
    assert {"env_check_gate.py", "worker_budget.py", "dispatch_gate.py",
            "recall_inject.py",
            "heartbeat_touch.py", "worker_pulse.py", "state_anchor.py",
            "completion_gate.py"} <= {
                c.replace("\\", "/").rsplit("/", 1)[-1]
                for c in _collect_commands(proj)}, \
        "rebuilt project settings must carry the full kunglao hook set"
