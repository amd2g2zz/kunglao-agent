# -*- coding: utf-8 -*-
"""Issue #372 — hook registry single-source (env_check mirror drift).

env_check.HOOK_FILES listed 6 hooks while wire_up_settings registers 8
distinct files (9 entries) — recall_inject (#268) and completion_gate were
absent from the mirror, so a settings rewrite silently dropping them still
passed the env_check hook gate (the #258 silent-drop class). This file pins
the single-source contract:

  1. wire_up_settings.WIRE_UP_HOOK_FILES is THE registry (the writer).
  2. env_check.HOOK_FILES must BE the registry (imported, not mirrored).
  3. check_hooks must scan the Stop section too — completion_gate is a Stop
     hook; a Pre/Post-only scan can never verify it (the same blind spot
     that hid the drift).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import env_check  # noqa: E402
import wire_up_settings  # noqa: E402


def test_registry_exists_in_wire_up_settings() -> None:
    """The writer exports WIRE_UP_HOOK_FILES — the single source."""
    files = wire_up_settings.WIRE_UP_HOOK_FILES
    assert isinstance(files, frozenset), "registry must be a frozenset (immutable)"
    # the 8 distinct files the registrations write today (issue #372)
    assert files == frozenset({
        "env_check_gate.py", "worker_budget.py", "dispatch_gate.py",
        "recall_inject.py", "heartbeat_touch.py", "worker_pulse.py",
        "state_anchor.py", "completion_gate.py",
    }), f"registry drifted from the actual registrations: {sorted(files)}"


def test_env_check_hook_files_is_the_registry() -> None:
    """env_check must derive its list FROM the registry — same object, not a
    hand-copied mirror (a copy is exactly what drifted in #372)."""
    assert env_check.HOOK_FILES is wire_up_settings.WIRE_UP_HOOK_FILES, (
        "env_check.HOOK_FILES must be the wire_up_settings registry itself "
        "(import it) — mirrored lists drift (#372)")
    assert "recall_inject.py" in env_check.HOOK_FILES
    assert "completion_gate.py" in env_check.HOOK_FILES


def test_check_hooks_scans_stop_section(tmp_path: Path) -> None:
    """check_hooks must collect commands from PreToolUse + PostToolUse AND
    Stop — completion_gate lives under Stop; a Pre/Post-only scan reports a
    completion_gate-less deployment as deployed (the #372 blind spot)."""
    import json

    ws = tmp_path / "ws"
    settings = ws / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    # every registry hook EXCEPT completion_gate (Stop) — must FAIL
    pre = {"matcher": "Agent", "hooks": [
        {"type": "command", "command": f"python /x/{h}"}
        for h in env_check.HOOK_FILES
        if h not in ("heartbeat_touch.py", "completion_gate.py")]}
    pre_bash = {"matcher": "Bash", "hooks": [
        {"type": "command", "command": "python /x/heartbeat_touch.py"}]}
    post = {"matcher": "Agent", "hooks": [
        {"type": "command", "command": f"python /x/{h}"}
        for h in env_check.HOOK_FILES if h == "worker_pulse.py"]}
    settings.write_text(json.dumps(
        {"hooks": {"PreToolUse": [pre, pre_bash], "PostToolUse": [post]}}),
        encoding="utf-8")
    ok, msg = env_check.check_hooks(ws)
    assert not ok, (
        "a deployment missing the Stop hook completion_gate.py must FAIL "
        f"(Stop section must be scanned): {msg}")
    assert "completion_gate.py" in msg
