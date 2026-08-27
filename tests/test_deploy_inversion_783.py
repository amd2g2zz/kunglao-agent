# -*- coding: utf-8 -*-
"""Issue #783 phase-2 — deployment-model inversion pins.

The workspace becomes SELF-CONTAINED once .claude/hooks is materialized:
registration resolves to the WORKSPACE-LOCAL copies with the workspace as
the uv project root, so later skill-package upgrades never mutate existing
workspaces (#783 ruling 2026-08-27). Workspaces without local copies fall
back to the canonical install (legacy behavior pinned too).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _commands(ws: Path) -> list[str]:
    settings = json.loads(
        (ws / ".claude" / "settings.json").read_text(encoding="utf-8"))
    return [h["command"]
            for face in settings.get("hooks", {}).values()
            for e in face for h in e.get("hooks", [])]


def test_register_invokes_ws_local_when_copies_materialized(tmp_path: Path) -> None:
    import hook_activation as ha

    ha.deploy_workspace_copy(tmp_path)          # materialize manifest
    count = ha.register_hooks(workspace=tmp_path)
    assert count > 0

    cmds = _commands(tmp_path)
    assert cmds, "registry must not be empty"
    for c in cmds:
        assert f"uv run --project {tmp_path.as_posix()}" in c, (
            f"#783: project root must be the workspace -- {c}")
        assert "/.claude/hooks/" in c.replace("\\", "/"), (
            f"script path must be the ws-local copy -- {c}")


def test_no_local_copies_falls_back_canonical(tmp_path: Path) -> None:
    import hook_activation as ha

    (tmp_path / ".claude").mkdir(parents=True)
    ha.register_hooks(workspace=tmp_path)

    cmds = _commands(tmp_path)
    assert cmds


def test_resolver_unit(tmp_path: Path):
    """Semantic pins: local copies -> inverted (project=ws); no local ->
    canonical dir with project=None."""
    from hook_activation import resolve_deployment

    ws_local = tmp_path / "ws" / ".claude" / "hooks"
    ws_local.mkdir(parents=True)
    d, proj = resolve_deployment(ws_local.parent.parent)
    assert proj == ws_local.parent.parent.resolve()
    assert d == ws_local.resolve()

    bare = tmp_path / "bare"
    bare.mkdir()
    d2, proj2 = resolve_deployment(bare)
    assert proj2 is None
    assert Path(d2).name == "hooks"


def test_upgrade_refresh_keeps_ws_copies_current(tmp_path: Path) -> None:
    """The #783 loop closes: init deploys -> skill-side copy drifts ->
    deployed_refresh restores workspace bytes from skill truth."""
    import hook_activation as ha
    from deployed_refresh import refresh

    ha.deploy_workspace_copy(tmp_path)
    ha.register_hooks(workspace=tmp_path)

    dst = tmp_path / ".claude" / "hooks" / "write_guard.py"
    original = dst.read_bytes()
    dst.write_bytes(original + b"\n# drifted\n")
    refresh(tmp_path)

    assert dst.read_bytes().startswith(original[:64]), (
        "upgrade must restore workspace bytes when the skill side moves")
