# -*- coding: utf-8 -*-
"""wire_up_settings.py - THE hook registry + a deprecated registration alias.

Issue #445 (2026-08-18): the WRITER that used to live here moved to
hook_activation.register_hooks (THE canonical registration entry, with the
post-write layer self-check). This module keeps two things:

  1. the REGISTRY (WIRE_UP_HOOK_FILES, HOOK_DEPLOYMENT_TARGETS,
     hook_deployment_targets, derive_hook_subset) — the data source every
     checker/writer derives from (#372/#381/#410 contracts). It is not a
     registration entry; moving it would churn four importers for zero
     convergence.
  2. wire_up_settings() — a DEPRECATED thin alias delegating to
     hook_activation.register_hooks (kept for the conservative #445
     migration; retirement is #446's job).

Issue #258 (2026-08-12): hook deployment is PROJECT-scoped. The pre-#258
hardcoded `Path.home()/.claude/settings.json` wrote hooks globally; in a
worktree (<HOME>/.claude/.wt-*/) that binds the hook commands to a path
that dies with the worktree — deleting the worktree silently killed all 8
hooks and blocked every session's tool calls. Project-level deployment makes
hooks live and die WITH the workspace: no global pollution, no stale
worktree-bound commands.

Issue #269 (2026-08-13): hook COMMAND paths are absolute and point at the
CANONICAL deployed skill install (~/.claude/skills/kunglao-agent/hooks) — a
--wire-up run from a dev worktree must not bind the commands to the
worktree path, which dies with the worktree (#228 lesson). The canonical
resolution now lives in hook_activation._canonical_hooks_dir / build_hook_entry.
"""
from __future__ import annotations

import warnings
from collections.abc import Iterable
from pathlib import Path

# #372: THE hook registry — every consumer derives from this frozenset.
# Pre-#372 env_check.py mirrored the list by hand and drifted (6 vs the 8
# files wire_up_settings actually registers — recall_inject/completion_gate
# silently invisible to the env_check deployment gate). The registrations
# below MUST keep this set in sync; tests/test_hook_registry_singlesource.py
# pins the set-equality so drift is loud. Deliberate narrow subsets
# (hooks_selfcheck.KONG_HOOK_FILES, external_kicker.KUNGLAO_HOOK_ENTRIES)
# pin their file sets to this registry via derive_hook_subset() below (#381).
WIRE_UP_HOOK_FILES = frozenset({
    "env_check_gate.py",       # PreToolUse/Agent — hard environment gate (#233)
    "worker_budget.py",        # Pre+PostToolUse/Agent — budget/tier enforcement
    "dispatch_gate.py",        # PreToolUse/Agent — dispatch contract gate
    "recall_inject.py",        # PreToolUse/Agent — runtime knowledge recall (#268)
    "heartbeat_touch.py",      # PreToolUse/Bash — liveness refresh on any tool use
    "worker_pulse.py",         # PostToolUse/Agent — completion pulse
    "state_anchor.py",         # PostToolUse/Agent — per-turn state re-anchor (#44)
    "completion_gate.py",      # Stop — code-owned completion gate (#55)
    "write_guard.py",          # PreToolUse/Edit|Write — contract-carrier write gate (#532)
})


# #410: THE deployment-target registry — where kunglao hooks are written and
# read. --wire-up writes the WORKSPACE-level file (the #258 PROJECT-scoped
# target), while the external_kicker's dead-session recovery reads/re-writes
# the WORKSPACE-PARENT file (D2: the gitignored settings carrying env secrets
# + mcpServers + block_malware_exec). env_check must accept BOTH — before
# #410 it checked only the ws-level file while the kicker re-registered the
# parent-level one, so a parent-wired workspace was reported 'hooks missing'
# (FAIL) with 'leave unwired' guidance — a self-contradiction. Every consumer
# derives its target set from this tuple (never a hand-mirrored path list);
# tests/test_hook_registry_singlesource.py pins the pair.
HOOK_DEPLOYMENT_TARGETS = (
    lambda ws: Path(ws).resolve() / ".claude" / "settings.json",          # #258 --wire-up target
    lambda ws: Path(ws).resolve().parent / ".claude" / "settings.json",   # external_kicker D2 target
)


def hook_deployment_targets(ws: Path | None) -> tuple[Path, Path]:
    """Resolve the project-level settings.json targets for a workspace.

    Issue #410: single source for hook deployment targets — the writer
    (wire_up_settings._settings_target / external_kicker D2) and the checker
    (env_check.check_hooks) must agree on where hooks live. Applies the
    HOOK_DEPLOYMENT_TARGETS registry and returns both project-level
    candidates, ws-level first (the #258 --wire-up target), then the
    workspace-parent (external_kicker D2 read/write target).
    """
    w = Path(ws).resolve()
    return tuple(fn(w) for fn in HOOK_DEPLOYMENT_TARGETS)


def derive_hook_subset(registry: Iterable[str], include: Iterable[str],
                       skip: Iterable[str], owner: str) -> frozenset[str]:
    """#381: validate a deliberate hook subset's tables against the registry.

    Subset mirrors (hooks_selfcheck's liveness chain, external_kicker's
    re-registration set) are DELIBERATELY narrower than WIRE_UP_HOOK_FILES,
    so they cannot be the registry by identity like env_check.HOOK_FILES.
    Instead each subset owns two semantic tables — `include` (the files it
    covers) and `skip` (the registry files it deliberately omits, with why) —
    and this validator pins the FILE SETS to the registry with loud
    invariants:

      - every `include` file must exist in the registry (a registry rename
        without a conscious mirror update raises);
      - every registry file must be accounted for by `include` | `skip` (a
        registry growth without a conscious table update raises);
      - every `skip` file must exist in the registry (a skip entry naming a
        file the registry no longer has is a stale deliberate omission);
      - `include` and `skip` must not overlap (a file cannot be both covered
        and deliberately omitted).

    Called at import time in both consumer modules, so a drifted registry
    fails loudly on every import instead of silently checking or
    re-registering a stale file set. Pure — validates and returns the
    `include` set as a frozenset, mutates nothing.
    """
    registry = frozenset(registry)
    include = frozenset(include)
    skip = frozenset(skip)
    unknown = include - registry
    unaccounted = registry - include - skip
    stale_skip = skip - registry   # skip names a file the registry no longer has
    overlap = include & skip       # covered AND deliberately omitted — contradiction
    if unknown or unaccounted or stale_skip or overlap:
        raise ValueError(
            f"{owner}: hook-subset tables drifted from the registry — table "
            f"files not in registry: {sorted(unknown)}; registry files in no "
            f"table: {sorted(unaccounted)}; skip files absent from registry: "
            f"{sorted(stale_skip)}; files in both include and skip: "
            f"{sorted(overlap)}. Update the subset tables deliberately "
            f"(issue #381).")
    return include




def wire_up_settings(workspace: Path | None = None,
                     global_opt_in: bool = False) -> int:
    """#445 DEPRECATED thin alias — hook_activation.register_hooks is THE
    canonical hook registration entry.

    Signature preserved for the conservative #445 migration (callers:
    tests + any external integrations); every call now warns and delegates.
    Retirement (deleting the alias) is issue #446 — NOT this change.

    See hook_activation.register_hooks for the actual behavior (the #258
    project-level target, the #269 canonical command paths, and the #445
    post-write self-check that FAILs a write landing on a layer that does
    not fire).
    """
    warnings.warn(
        "wire_up_settings.wire_up_settings is deprecated (#445): the hook "
        "registration entry is hook_activation.register_hooks (CLI: "
        "hook_activation.py <workspace> --wire-up). Retirement: #446.",
        DeprecationWarning, stacklevel=2)
    from hook_activation import register_hooks
    return register_hooks(workspace=workspace, global_opt_in=global_opt_in)
