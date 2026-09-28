# -*- coding: utf-8 -*-
"""Issue #783 — deployed-mode registration e2e (--deploy-local).

Pins the inverted deployment contract: the workspace .claude tree becomes
self-contained (manifest copies present) and the written settings commands
target the WORKSPACE copies with `uv run --project <workspace>`; a second
run is idempotent at the file level.
"""
from __future__ import annotations

import json
import hook_activation as ha
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _cli(ws: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "hook_activation.py"),
         "--deploy-local", str(ws)],
        capture_output=True, text=True)


def test_deploy_local_e2e(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    r1 = _cli(ws)
    assert r1.returncode == 0, r1.stderr

    hooks_dir = ws / ".claude" / "hooks"
    assert (hooks_dir / "dispatch_gate.py").is_file(), "hooks copied"
    assert (ws / ".claude" / "agents" / "kunglao-worker.md").is_file(), (
        "subagent definitions copied")

    settings = json.loads((ws / ".claude" / "settings.json")
                          .read_text(encoding="utf-8"))
    cmds = [h["command"] for face in settings["hooks"].values()
            for e in face for h in e.get("hooks", [])]
    assert cmds, "registry registered"
    # 0.1.6 sweep (#6): env project = framework root; script path = ws copy
    for c in cmds:
        assert f"uv run --project {ha._framework_project_root()}" in c and             " python " in c, (
            f"#6: env project must be the framework root: {c}")
        assert f"{ws.as_posix()}/.claude/hooks/" in c, (
            f"#783: script path stays the workspace copy: {c}")
        assert "/.claude/hooks/" in c.replace("\\", "/"), (
            f"script path must be the workspace-local copy: {c}")

    # idempotency: second run changes nothing material
    before = {p.name: p.read_bytes() for p in hooks_dir.glob("*.py")}
    r2 = _cli(ws)
    assert r2.returncode == 0, r2.stderr
    after = {p.name: p.read_bytes() for p in hooks_dir.glob("*.py")}
    assert before == after
