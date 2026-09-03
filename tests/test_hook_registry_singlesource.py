# -*- coding: utf-8 -*-
"""Issue #372/#381 — hook registry single-source (mirror drift).

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

Issue #381 extends the contract to the two DELIBERATE narrow subsets that
survive #372 — hooks_selfcheck.KONG_HOOK_FILES (4-hook liveness chain) and
external_kicker.KUNGLAO_HOOK_ENTRIES (5-entry dead-session bootstrap). A
subset cannot be the registry by identity, so each pins its FILE SET to the
registry via wire_up_settings.derive_hook_subset, which raises on any
registry rename/growth at import — a hardcoded mirror would drift silently
(re-registering stale names, skipping new ones) with no test failing.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import env_check  # noqa: E402
import external_kicker  # noqa: E402
import hooks_selfcheck  # noqa: E402
import wire_up_settings  # noqa: E402


def test_registry_exists_in_wire_up_settings() -> None:
    """The writer exports WIRE_UP_HOOK_FILES — the single source."""
    files = wire_up_settings.WIRE_UP_HOOK_FILES
    assert isinstance(files, frozenset), "registry must be a frozenset (immutable)"
    # the 9 distinct files the registrations write today (#372 baseline 8
    # + #532 write_guard on the Edit|Write|MultiEdit matcher)
    assert files == frozenset({
        "env_check_gate.py", "worker_budget.py", "dispatch_gate.py",
        "recall_inject.py", "heartbeat_touch.py", "worker_pulse.py",
        "state_anchor.py", "completion_gate.py", "write_guard.py",
        "orchestrator_tool_guard.py",  # #608 Bash maker-checker WARN
        "violation_capture.py",        # #718 Bash violation recorder
        "bash_fact_guard.py",          # #809 Bash facts-write lint recorder
    }), f"registry drifted from the actual registrations: {sorted(files)}"


def test_double_registered_hooks_sentinel() -> None:
    """#675: the double-registration set is pinned HERE (the sentinel
    file — deriving it from the registry would be tautological). Every
    tests/-side count anchor derives its extra registration from this
    export, so membership drift must be loud and deliberate."""
    doubled = wire_up_settings.DOUBLE_REGISTERED_HOOKS
    assert isinstance(doubled, frozenset), (
        "DOUBLE_REGISTERED_HOOKS must be a frozenset (immutable)")
    assert doubled == frozenset({"worker_budget.py",
                                 # #601: second PreToolUse matcher row — MCP
                                 # host-channel face beside the Bash face
                                 "orchestrator_tool_guard.py"}), (
        f"DOUBLE_REGISTERED_HOOKS drifted: {sorted(doubled)} — a membership "
        "change means register_hooks double-registers differently; update "
        "this sentinel deliberately and verify the count anchors follow")


def test_env_check_hook_files_is_the_registry() -> None:
    """env_check must derive its list FROM the registry — same object, not a
    hand-copied mirror (a copy is exactly what drifted in #372)."""
    assert env_check.HOOK_FILES is wire_up_settings.WIRE_UP_HOOK_FILES, (
        "env_check.HOOK_FILES must be the wire_up_settings registry itself "
        "(import it) — mirrored lists drift (#372)")
    assert "recall_inject.py" in env_check.HOOK_FILES
    assert "completion_gate.py" in env_check.HOOK_FILES


# ---------- #410: deployment-target single-source ----------

def test_wire_up_settings_exports_hook_deployment_targets() -> None:
    """The writer must export the deployment-target registry — the single
    source of truth for where hooks are read/written (issue #410). Both
    project-level targets that hooks can live in must be listed."""
    targets = wire_up_settings.HOOK_DEPLOYMENT_TARGETS
    assert isinstance(targets, tuple), "deployment targets must be an immutable tuple"
    assert len(targets) == 2, (
        "exactly two project-level targets: <ws>/.claude/settings.json (#258) "
        "and <ws-parent>/.claude/settings.json (external_kicker D2, #410)")
    assert all(callable(fn) for fn in targets), \
        "each target must be a resolver callable (ws -> Path)"

    ws_level, parent_level = [fn(Path("ws")) for fn in targets]
    # as_posix(): str(Path) yields native separators (backslashes on win32) —
    # compare through the separator-stable lens, same exactness (#457 triage #7).
    assert ws_level.as_posix().endswith("ws/.claude/settings.json"), \
        f"target[0] must resolve to the ws-level file: {ws_level}"
    assert parent_level.as_posix().endswith(".claude/settings.json"), \
        f"target[1] must resolve to a workspace-parent file: {parent_level}"
    assert parent_level.parent.parent == Path("ws").resolve().parent, \
        "target[1] must be the PARENT of the workspace: <ws-parent>/.claude/settings.json"


def test_hook_deployment_targets_helper_matches_registry() -> None:
    """hook_deployment_targets(ws) is the callable registry applied — the
    convenience helper env_check/external_kicker consume."""
    ws = Path("ws")
    resolved = wire_up_settings.hook_deployment_targets(ws)
    assert resolved == (
        Path("ws").resolve() / ".claude" / "settings.json",
        Path("ws").resolve().parent / ".claude" / "settings.json",
    )


def test_external_kicker_default_settings_path_derives_from_registry() -> None:
    """#410: the external_kicker's default project settings path must derive
    from the wire_up_settings target registry, not a hand-written literal —
    deployment target and check location must share one source (the #410
    self-contradiction: external_kicker read <ws-parent>, env_check checked
    <ws>)."""
    ws = Path("ws")
    assert external_kicker.default_settings_path(ws) == (
        wire_up_settings.hook_deployment_targets(ws)[1]), (
        "kicker default must match the registry's workspace-parent target (#410)")


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
    # #410: check_hooks is TRI-STATE — (status, msg) with status in
    # PASS|WARN|FAIL. A partial deployment (a target file exists but the
    # Stop hook completion_gate.py is missing) must be FAIL.
    status, msg = env_check.check_hooks(ws)
    assert status == "FAIL", (
        "a deployment missing the Stop hook completion_gate.py must FAIL "
        f"(Stop section must be scanned): {msg}")
    assert "completion_gate.py" in msg


# ---------------------------------------------------------------------------
# #381: the two deliberate subset mirrors (KONG_HOOK_FILES / KUNGLAO_HOOK_ENTRIES)
# ---------------------------------------------------------------------------
# Derivation cannot be identity like env_check's HOOK_FILES — a subset keeps
# its own semantic tables (the 4-hook liveness chain; the 5-entry bootstrap
# with matchers). The contract instead: every table file must exist in the
# registry (rename loud) and every registry file must be accounted for by a
# table (growth loud) — via wire_up_settings.derive_hook_subset, run at
# import time in both consumer modules. The drift tests below simulate a
# renamed/added registry file; a hardcoded mirror would pass silently.

KONG_CHAIN = ["heartbeat_touch.py", "worker_budget.py",
              "dispatch_gate.py", "worker_pulse.py"]
KONG_SKIP = {"env_check_gate.py", "recall_inject.py",
             "state_anchor.py", "completion_gate.py", "write_guard.py",
             "orchestrator_tool_guard.py",
             "violation_capture.py",
             "bash_fact_guard.py"}  # #809
KICKER_FILES = {"worker_budget.py", "dispatch_gate.py",
                "heartbeat_touch.py", "worker_pulse.py"}


def test_kong_hook_files_exact_liveness_subset() -> None:
    """KONG_HOOK_FILES is exactly the 4-hook liveness chain, and its chain +
    skip tables partition the registry — no unaccounted registry file."""
    assert hooks_selfcheck.KONG_HOOK_FILES == KONG_CHAIN
    assert set(hooks_selfcheck.KONG_HOOK_FILES) <= wire_up_settings.WIRE_UP_HOOK_FILES
    assert set(hooks_selfcheck.KONG_HOOK_FILES) | KONG_SKIP == set(
        wire_up_settings.WIRE_UP_HOOK_FILES), (
        "chain + skip tables must partition the registry — a registry file "
        "in no table drifts silently (#381)")


def test_kicker_entries_exact_five_with_matchers() -> None:
    """The kicker's 5-entry table is semantic (worker_budget fires Pre+Post,
    heartbeat_touch is Bash-scoped) — pin it exactly so a change to the
    deliberate subset is a conscious edit, and its files must sit inside the
    registry."""
    assert external_kicker.KUNGLAO_HOOK_ENTRIES == [
        ("PreToolUse", "Agent", "worker_budget.py"),
        ("PreToolUse", "Agent", "dispatch_gate.py"),
        ("PreToolUse", "Bash", "heartbeat_touch.py"),
        ("PostToolUse", "Agent", "worker_budget.py"),
        ("PostToolUse", "Agent", "worker_pulse.py"),
    ]
    files = {f for _, _, f in external_kicker.KUNGLAO_HOOK_ENTRIES}
    assert files == KICKER_FILES
    assert files <= wire_up_settings.WIRE_UP_HOOK_FILES
    assert files | KONG_SKIP == set(wire_up_settings.WIRE_UP_HOOK_FILES), (
        "kicker entry files + skip files must partition the registry (#381)")


def test_derive_hook_subset_returns_include_when_tables_cover_registry() -> None:
    """Valid tables → the include set comes back unchanged (the derivation is
    validation + pass-through; the subset content stays table-owned)."""
    out = wire_up_settings.derive_hook_subset(
        wire_up_settings.WIRE_UP_HOOK_FILES,
        include=set(KONG_CHAIN), skip=KONG_SKIP, owner="test")
    assert out == set(KONG_CHAIN)


def test_derive_hook_subset_raises_on_registry_rename() -> None:
    """A registry rename of a mirrored file must be LOUD — a hardcoded mirror
    would keep checking/re-registering the old name forever (the drift)."""
    renamed = (wire_up_settings.WIRE_UP_HOOK_FILES
               - {"heartbeat_touch.py"}) | {"heartbeat_touch_v2.py"}
    with pytest.raises(ValueError, match="heartbeat_touch.py"):
        wire_up_settings.derive_hook_subset(
            renamed, include=set(KONG_CHAIN), skip=KONG_SKIP, owner="test")


def test_derive_hook_subset_raises_on_registry_growth() -> None:
    """A 9th registry file must be LOUD — neither table accounts for it, so a
    conscious table update (chain or skip) is forced instead of a silent miss."""
    grown = wire_up_settings.WIRE_UP_HOOK_FILES | {"new_hook.py"}
    with pytest.raises(ValueError, match="new_hook.py"):
        wire_up_settings.derive_hook_subset(
            grown, include=set(KONG_CHAIN), skip=KONG_SKIP, owner="test")


def test_derive_hook_subset_flags_stale_skip() -> None:
    """A skip entry naming a file the registry no longer has is drift too: the
    table claims a deliberate omission that no longer exists. Silent today —
    only unknown (include - registry) and unaccounted are checked, and a
    shrunk registry with a stale skip entry hits neither."""
    shrunk = wire_up_settings.WIRE_UP_HOOK_FILES - {"completion_gate.py"}
    with pytest.raises(ValueError, match="completion_gate.py"):
        wire_up_settings.derive_hook_subset(
            shrunk, include=set(KONG_CHAIN), skip=KONG_SKIP, owner="test")


def test_derive_hook_subset_flags_include_skip_overlap() -> None:
    """A file in BOTH include and skip is a contradictory table — covered and
    deliberately omitted at once. Silent today: unknown and unaccounted are
    both empty, so the overlap passes."""
    with pytest.raises(ValueError, match="completion_gate.py"):
        wire_up_settings.derive_hook_subset(
            wire_up_settings.WIRE_UP_HOOK_FILES,
            include=set(KONG_CHAIN) | {"completion_gate.py"},
            skip=KONG_SKIP, owner="test")


def test_kong_module_import_raises_on_registry_growth(monkeypatch) -> None:
    """Module-level derivation: growing the registry must make `import
    hooks_selfcheck` RAISE — a hardcoded mirror imports fine and checks its
    stale 4 forever (today's silent behavior; the RED for #381)."""
    grown = wire_up_settings.WIRE_UP_HOOK_FILES | {"new_hook.py"}
    monkeypatch.setattr(wire_up_settings, "WIRE_UP_HOOK_FILES", grown)
    sys.modules.pop("hooks_selfcheck", None)
    try:
        with pytest.raises(ValueError, match="new_hook.py"):
            importlib.import_module("hooks_selfcheck")
    finally:
        # drop the failed half-import only — NO restore here: the registry
        # patch is still active inside finally, so a re-import would raise
        # again. After monkeypatch teardown the next import (any consumer,
        # e.g. test_wire_up_settings._run_selfcheck) re-executes cleanly
        # against the real registry.
        sys.modules.pop("hooks_selfcheck", None)


def test_kicker_module_import_raises_on_registry_growth(monkeypatch) -> None:
    """Module-level derivation for the kicker: a grown registry must make
    `import external_kicker` RAISE — the kicker must not silently keep
    re-registering its stale 5-entry set while a new hook exists."""
    grown = wire_up_settings.WIRE_UP_HOOK_FILES | {"another_hook.py"}
    monkeypatch.setattr(wire_up_settings, "WIRE_UP_HOOK_FILES", grown)
    sys.modules.pop("external_kicker", None)
    try:
        with pytest.raises(ValueError, match="another_hook.py"):
            importlib.import_module("external_kicker")
    finally:
        # same as above: pop the half-import; the patch is still active, so
        # the clean re-import happens on the NEXT import after teardown.
        sys.modules.pop("external_kicker", None)
