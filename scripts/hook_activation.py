# -*- coding: utf-8 -*-
"""hook_activation.py - selective hook activation for kunglao-agent (core).

User pain point: "kunglao-agent 需要安装hook，但是只有被激活的时候hook才生效，
否则会产生大量噪声给 kunglao-agent"

kunglao-agent has 7+ enforcement hooks (active_intervention, cost_gate,
backtrack_gate, reuse_gate, memory_capture, etc.). Running ALL of them on EVERY
orchestrator turn produces too much noise. This script implements selective
activation: kunglao-agent decides per-hook whether it should fire, based on:
  - current cost_advice tier (from cost_gate.py)
  - current iteration phase (DISPATCH / MONITOR / VERIFY / IDLE)
  - explicit user override

Wire-up:
  - Each hook checks .hook_state.json BEFORE running
  - If a hook is not in "active" state, it exits 0 (no-op) immediately
  - This script writes .hook_state.json with the active set

State file schema (memory/.hook_state.json):
  {
    "ts": "<ISO 8601 UTC>",
    "tier": "advisory | pause_non_essential | HARD_PAUSE | none",
    "phase": "DISPATCH | MONITOR | VERIFY | IDLE",
    "active_hooks": ["active_intervention", "cost_gate"],
    "paused_hooks": ["backtrack_gate"],
    "user_override": {"<hook_name>": "on" | "off"},
    "expires_at": "<ISO 8601 UTC — activation expires; renew with --renew>"
  }

Usage:
  python hook_activation.py <workspace> [--set-active h1,h2] [--set-paused h3] [--phase X]
  python hook_activation.py <workspace> --renew          # refresh expiry (kunglao-agent Phase 0)
  python hook_activation.py <workspace> --is-active dispatch_gate
  python hook_activation.py <workspace> --wire-up        # register hooks in <workspace>/.claude/settings.json (PROJECT-level, #258)
  python hook_activation.py <workspace> --heartbeat-off  # CONVERGED 后停心跳 (issue #237)

T-2 split (2026-08-11): the --wire-up / --reconcile / --heartbeat-* jobs now
live in wire_up_settings.py / reconcile_workers.py / heartbeat.py; main()
dispatches to them. The public API below (read_state, write_state, is_active,
is_active_strict, update_state, renew) is unchanged — 7 gate scripts + hooks
import this module as `ha`.

Issue #258 (2026-08-12): --wire-up deploys to the PROJECT-level
<workspace>/.claude/settings.json — never the user-global ~/.claude/settings.json
(the pre-#258 default bound hooks to a worktree path that died with the
worktree; 8 hooks went silent at once). wire_up_settings(global_opt_in=True)
is the ONLY escape hatch, explicit opt-in with a stderr warning.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOOK_STATE_FILE = ".hook_state.json"
DEFAULT_TTL_MINUTES = 30
# Activation is short-lived BY DESIGN: the orchestrator must renew every
# 30 min or the hooks sleep. This makes activation a real liveness signal —
# a stale activation from a dead/abandoned session cannot keep firing hooks.
# ONLY the orchestrator may activate/renew; subagents are forbidden
# (kunglao-worker.md hard rule).
ALL_HOOKS = {
    "active_intervention",
    "cost_gate",
    "backtrack_gate",
    "reuse_gate",
    "troubleshooting_gate",
    "search_gate",
    "memory_capture",
    "dispatch_gate",
    "worker_pulse",
    "state_anchor",
    "completion_gate",
}

TIER_DEFAULTS = {
    "advisory": {"active": ["active_intervention", "cost_gate"],
                  "paused": []},
    "pause_non_essential": {"active": ["active_intervention", "cost_gate"],
                            "paused": ["reuse_gate"]},
    "HARD_PAUSE": {"active": ["cost_gate"],
                   "paused": ["active_intervention",
                              "reuse_gate", "backtrack_gate", "search_gate",
                              "troubleshooting_gate"]},
    "none": {"active": sorted(ALL_HOOKS),
             "paused": []},
}


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_state(workspace: Path) -> dict:
    path = workspace / HOOK_STATE_FILE
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def write_state(workspace: Path, state: dict) -> None:
    path = workspace / HOOK_STATE_FILE
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def is_active(workspace: Path, hook_name: str) -> bool:
    """Check whether a hook should fire. Returns True if active, False if paused.

    Expiry: if the state carries an expires_at in the past, the activation is
    STALE and the hook is treated as inactive. A stale activation from a
    5-day-old session must not keep firing hooks in a fresh session —
    kunglao-agent renews at Phase 0 (`--renew`)."""
    state = read_state(workspace)
    if not state:
        return True
    expires = state.get("expires_at")
    if expires:
        try:
            exp = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            if datetime.now(tz=timezone.utc) > exp:
                return False  # expired — treated as paused
        except (ValueError, TypeError):
            pass  # unparseable expiry: don't block on it, fall through
    override = state.get("user_override", {}).get(hook_name)
    if override == "on":
        return True
    if override == "off":
        return False
    active = state.get("active_hooks", [])
    paused = state.get("paused_hooks", [])
    if hook_name in paused:
        return False
    if hook_name in active:
        return True
    return True


def is_active_strict(workspace: Path, hook_name: str) -> bool:
    """Hooks use THIS, not is_active().

    is_active() defaults to True when no state file exists (legacy: an
    unconfigured workspace must not silently disable enforcement). That is the
    WRONG default for the new narrow hooks (dispatch_gate, worker_pulse):
    semantics = default-INACTIVE — no activation → hooks sleep. A
    non-kunglao-agent session must get zero noise from these hooks.

    Strict = explicit activation required AND not expired AND not paused.
    is_active() keeps its legacy behavior for the old gate family."""
    state = read_state(workspace)
    if not state:
        return False  # default-inactive: no activation, no firing
    expires = state.get("expires_at")
    if expires:
        try:
            exp = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            if datetime.now(tz=timezone.utc) > exp:
                return False
        except (ValueError, TypeError):
            return False  # unparseable expiry → treat as stale, don't fire
    override = state.get("user_override", {}).get(hook_name)
    if override == "on":
        return True
    if override == "off":
        return False
    active = state.get("active_hooks", [])
    paused = state.get("paused_hooks", [])
    if hook_name in paused:
        return False
    return hook_name in active


def update_state(workspace: Path, tier: str, phase: str,
                 set_active=None,
                 set_paused=None,
                 user_override=None,
                 ttl_minutes: int = DEFAULT_TTL_MINUTES) -> dict:
    defaults = TIER_DEFAULTS.get(tier, TIER_DEFAULTS["none"])
    active = set_active if set_active is not None else defaults["active"]
    paused = set_paused if set_paused is not None else defaults["paused"]

    state = read_state(workspace)
    overrides = dict(state.get("user_override", {}))
    if user_override:
        overrides.update(user_override)

    for h in active + paused:
        if h not in ALL_HOOKS:
            raise ValueError(f"unknown hook: {h}; valid hooks: {sorted(ALL_HOOKS)}")

    new_state = {
        "ts": utc_now(),
        "tier": tier,
        "phase": phase,
        "active_hooks": active,
        "paused_hooks": paused,
        "user_override": overrides,
        "expires_at": (datetime.now(tz=timezone.utc) + timedelta(minutes=ttl_minutes)).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    write_state(workspace, new_state)
    return new_state


def renew(workspace: Path, ttl_minutes: int = DEFAULT_TTL_MINUTES) -> dict:
    """Refresh the activation expiry WITHOUT changing tier/phase/hook sets.
    Called by the orchestrator (never a subagent) at Phase 0 and every heartbeat
    tick. If the activation has expired, this re-activates with the current sets.
    Also refreshes .heartbeat.json last_tick_ts — a renewing tick IS the proof
    the heartbeat is alive (--heartbeat-check keys off this)."""
    state = read_state(workspace)
    if not state:
        # no prior activation — activate the default set
        return update_state(workspace, "none", "IDLE", ttl_minutes=ttl_minutes)
    state["ts"] = utc_now()
    state["expires_at"] = (datetime.now(tz=timezone.utc) + timedelta(minutes=ttl_minutes)).isoformat(timespec="seconds").replace("+00:00", "Z")
    write_state(workspace, state)
    # heartbeat liveness = renew ticks (only if registered)
    hb = workspace / "runs" / ".heartbeat.json"
    if hb.exists():
        try:
            import json as _json
            hstate = _json.loads(hb.read_text(encoding="utf-8"))
            hstate["last_tick_ts"] = utc_now()
            hb.write_text(_json.dumps(hstate, indent=2), encoding="utf-8")
        except Exception:
            pass  # heartbeat file corrupt — --heartbeat-check will report it
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description="Selective hook activation for kunglao-agent")
    parser.add_argument("workspace", help="workspace root")
    parser.add_argument("--set-active", type=str, default=None,
                        help="comma-separated hook names to mark active")
    parser.add_argument("--set-paused", type=str, default=None,
                        help="comma-separated hook names to mark paused")
    parser.add_argument("--tier", choices=list(TIER_DEFAULTS.keys()), default="none",
                        help="cost tier; auto-selects default active/paused sets")
    parser.add_argument("--phase", choices=["DISPATCH", "MONITOR", "VERIFY", "IDLE"],
                        default="IDLE", help="current orchestrator phase")
    parser.add_argument("--user-override", type=str, default=None,
                        help='per-hook user override, format "hook1=on,hook2=off"')
    parser.add_argument("--is-active", type=str, default=None,
                        help="if set, just check this hook and print active/inactive + exit 0/1")
    parser.add_argument("--renew", action="store_true",
                        help="refresh activation expiry (orchestrator-only; subagents forbidden)")
    parser.add_argument("--wire-up", action="store_true",
                        help="register kunglao-agent hooks in <workspace>/.claude/settings.json "
                             "(project-level; NOT global — issue #258: the pre-#258 default wrote "
                             "the user-global settings, binding hooks to a worktree path that dies "
                             "with the worktree). Idempotent: merges into existing hooks config, "
                             "preserves other keys. Called at Phase 0 by the orchestrator; fixes "
                             "'hooks never fired' recurrences.")
    parser.add_argument("--reconcile", action="store_true",
                        help="rebuild [active_workers] from the GROUND TRUTH — worker status "
                             "files in every .wt-*/ worktree (last status line == in-progress). Removes "
                             "zombie entries that accumulate when PostToolUse remove_worker never fires "
                             "(hooks not wired). Call at Phase 0 and every heartbeat tick.")
    parser.add_argument("--heartbeat-on", action="store_true",
                        help="REGISTER the heartbeat as a verifiable state — writes "
                             "<ws>/runs/.heartbeat.json {started_ts, interval_min, cron_id} so "
                             "'monitoring is running' is a checked file state, not a self-claim. "
                             "Call at Phase 0 right after the /loop cron is created.")
    parser.add_argument("--heartbeat-check", action="store_true",
                        help="VERIFY the heartbeat is actually registered — exit 0 if "
                             "<ws>/runs/.heartbeat.json exists and is < 35 min old (cron tick should "
                             "have refreshed it); exit 1 if missing/stale = monitoring is NOT running. "
                             "Call every heartbeat tick and before declaring CONVERGED.")
    parser.add_argument("--heartbeat-off", action="store_true",
                        help="STOP the heartbeat (converged teardown, issue #237 dual-constraint) — "
                             "deletes <ws>/runs/.heartbeat.json ONLY when convergence_check.py returns "
                             "CONVERGED (exit 0), else rejects with guidance. Cleaning up early breaks "
                             "dispatch gating (check_heartbeat_alive); cleaning up late burns tokens on "
                             "idle cron wakes. --force bypasses the guard (explicit override).")
    parser.add_argument("--force", action="store_true",
                        help="bypass --heartbeat-off preconditions (explicit operator override; "
                             "only used when the orchestrator has a mechanical reason to stop "
                             "an unconverged heartbeat)")
    args = parser.parse_args()

    workspace = Path(args.workspace)

    # T-2 split: delegated jobs live in focused modules
    if args.wire_up:
        from wire_up_settings import wire_up_settings
        n = wire_up_settings(workspace=workspace)
        target = workspace / ".claude" / "settings.json"
        print(f"OK: kunglao-agent hooks wired into {target} ({n} entries)")
        return 0

    if args.heartbeat_on:
        from heartbeat import heartbeat_register
        return heartbeat_register(workspace)

    if args.heartbeat_check:
        from heartbeat import heartbeat_check
        return heartbeat_check(workspace)

    if args.heartbeat_off:
        from heartbeat import heartbeat_off
        return heartbeat_off(workspace, force=args.force)

    if args.reconcile:
        from reconcile_workers import reconcile_workers
        n = reconcile_workers(workspace)
        print(f"OK: active_workers reconciled from worktree status files ({n} active)")
        return 0

    if args.renew:
        state = renew(workspace)
        print(f"OK: activation renewed until {state.get('expires_at')}")
        print(f"  tier={state.get('tier')} phase={state.get('phase')}")
        return 0

    if args.is_active:
        active = is_active(workspace, args.is_active)
        print(f"{args.is_active}: {'ACTIVE' if active else 'PAUSED'}")
        return 0 if active else 1

    set_active = args.set_active.split(",") if args.set_active else None
    set_paused = args.set_paused.split(",") if args.set_paused else None
    overrides = {}
    if args.user_override:
        for kv in args.user_override.split(","):
            k, _, v = kv.partition("=")
            overrides[k.strip()] = v.strip()

    state = update_state(workspace, args.tier, args.phase,
                        set_active=set_active, set_paused=set_paused,
                        user_override=overrides)
    print(f"OK: state updated")
    print(f"  tier={state['tier']} phase={state['phase']}")
    print(f"  active: {', '.join(state['active_hooks'])}")
    print(f"  paused: {', '.join(state['paused_hooks'])}")
    if state["user_override"]:
        print(f"  user_override: {state['user_override']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
