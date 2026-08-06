"""hook_activation.py - selective hook activation for kunglao-agent.

User pain point: "kunglao-agent 需要安装hook，但是只有被激活的时候hook才生效，
否则会产生大量噪声给 kunglao-agent"

kunglao-agent has 7+ enforcement hooks (active_intervention, doubt_checker, cost_gate,
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
    "paused_hooks": ["memory_capture", "backtrack_gate"],
    "user_override": {"<hook_name>": "on" | "off"},
    "expires_at": "<ISO 8601 UTC — activation expires; renew with --renew>"
  }

Usage:
  python hook_activation.py <workspace> [--set-active h1,h2] [--set-paused h3] [--phase X]
  python hook_activation.py <workspace> --renew          # refresh expiry (kunglao-agent Phase 0)
  python hook_activation.py <workspace> --is-active dispatch_gate
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOOK_STATE_FILE = ".hook_state.json"
DEFAULT_TTL_MINUTES = 30
# Activation is short-lived BY DESIGN (v1.9.7): the orchestrator must renew
# every 30 min or the hooks sleep. This makes activation a real liveness
# signal — a stale activation from a dead/abandoned session cannot keep
# firing hooks. ONLY the orchestrator may activate/renew; subagents are
# forbidden (kunglao-worker.md hard rule).
ALL_HOOKS = {
    "active_intervention",
    "doubt_checker",
    "cost_gate",
    "backtrack_gate",
    "reuse_gate",
    "troubleshooting_gate",
    "search_gate",
    "memory_capture",
    "dispatch_gate",
    "worker_pulse",
}

TIER_DEFAULTS = {
    "advisory": {"active": ["active_intervention", "cost_gate", "doubt_checker"],
                  "paused": ["memory_capture"]},
    "pause_non_essential": {"active": ["active_intervention", "cost_gate"],
                            "paused": ["memory_capture", "doubt_checker", "reuse_gate"]},
    "HARD_PAUSE": {"active": ["cost_gate"],
                   "paused": ["active_intervention", "memory_capture", "doubt_checker",
                              "reuse_gate", "backtrack_gate", "search_gate",
                              "troubleshooting_gate"]},
    "none": {"active": sorted(ALL_HOOKS),
             "paused": []},
}


def _wire_up_settings() -> int:
    """v1.9.18: register kunglao-agent hooks in the global settings.json.

    Idempotent merge: reads current settings, appends our hook entries under
    PreToolUse/PostToolUse with matcher "Agent", skips entries that already
    exist (same command path), preserves every other key. Writes back with
    4-space indent. Returns the number of hook entries registered.
    """
    import json as _json

    settings_path = Path.home() / ".claude" / "settings.json"
    existing = {}
    if settings_path.exists():
        try:
            existing = _json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    hooks = existing.get("hooks") or {}
    pre = hooks.get("PreToolUse") or []
    post = hooks.get("PostToolUse") or []

    hook_dir = Path(__file__).resolve().parent.parent / "hooks"

    def _entry(hook_file: str) -> dict:
        # POSIX path (forward slashes): hooks run via `sh -c` — Windows
        # backslash paths get their backslashes eaten as escape chars
        # (C:\Users\... -> C:Users...). v1.9.18 fix.
        p = (hook_dir / hook_file).as_posix()
        return {"type": "command", "command": f"python {p}"}

    def _ensure(entries: list, matcher: str, hook_file: str) -> tuple[list, bool]:
        new = [e for e in entries if e.get("matcher") == matcher]
        other = [e for e in entries if e.get("matcher") != matcher]
        # v1.9.18: remove legacy entries with the same basename (backslash paths
        # from pre-posix wire-up) so re-wiring replaces them, not stacks.
        new = [
            e for e in new
            if not any((h.get("command", "").replace("\\", "/").rsplit("/", 1)[-1] == hook_file) for h in e.get("hooks", []))
        ]
        new.append({"matcher": matcher, "hooks": [_entry(hook_file)]})
        return other + new, True

    count = 0
    pre, added = _ensure(pre, "Agent", "worker_budget.py")
    count += added
    pre, added = _ensure(pre, "Agent", "dispatch_gate.py")
    count += added
    # v1.9.36: heartbeat_touch on matcher=Bash — ANY tool activity refreshes
    # last_tick_ts, decoupling heartbeat liveness from orchestrator cognition
    # (root-cause fix for '整个属于心跳的BUG': stale heartbeat gate rejected
    # dispatches whenever the orchestrator was busy/compacted).
    pre, added = _ensure(pre, "Bash", "heartbeat_touch.py")
    count += added
    post, added = _ensure(post, "Agent", "worker_budget.py")
    count += added
    post, added = _ensure(post, "Agent", "worker_pulse.py")
    count += added

    hooks["PreToolUse"] = pre
    hooks["PostToolUse"] = post
    existing["hooks"] = hooks
    settings_path.write_text(
        _json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return count


def _reconcile_workers(workspace: Path) -> int:
    """v1.9.18: rebuild [active_workers] from worktree status files.

    GROUND TRUTH = runs/worker-status-*.md in every .wt-*/ worktree (and the
    main workspace runs/): a worker is ACTIVE iff its LAST status line says
    "in-progress". This removes zombie [active_workers] entries that appear
    when the PostToolUse remove_worker hook never fires (hooks not wired /
    settings.json rewritten). Returns the active count.
    """
    import re as _re

    status_re = _re.compile(r"status:\s*(\S+)")
    active_ids = set()
    dirs = [workspace / "runs"]
    try:
        dirs += sorted(workspace.parent.glob(".wt-*/malware-analysis-workspace/runs"))
    except OSError:
        pass
    for runs in dirs:
        if not runs.is_dir():
            continue
        for p in runs.glob("worker-status-*.md"):
            last = None
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                m = status_re.search(line)
                if m:
                    last = m.group(1).lower()
            if last == "in-progress":
                active_ids.add(p.stem)
        # v1.9.37: red-team verifiers write plan-redteam-*.md (start) + verify-redteam-*.md (end).
        # ACTIVE iff plan exists but its verify report is not yet written. This closes the
        # "reconcile shows 1 active while 3 agents actually run" gap (red-team was invisible).
        for p in runs.glob("plan-redteam-*.md"):
            target = p.stem[len("plan-redteam-"):]
            if not (runs / f"verify-redteam-{target}.md").exists():
                active_ids.add(f"verifier-redteam-{target}")

    # rewrite the [active_workers] segment of analysis_state.txt
    state_path = workspace / "analysis_state.txt"
    text = state_path.read_text(encoding="utf-8", errors="replace")
    seg_re = _re.compile(r"\[active_workers\].*?\[/active_workers\]", _re.DOTALL)
    entries = [f"worker_id={wid} | claim_id= | dispatched_at=0 | tier=0 | tools=" for wid in sorted(active_ids)]
    block = "[active_workers]\n" + "\n".join(entries) + ("\n" if entries else "") + "[/active_workers]"
    new_text, n_subs = seg_re.subn(block, text, count=1)
    if n_subs == 0:
        new_text = text.rstrip("\n") + "\n\n" + block + "\n"
    state_path.write_text(new_text, encoding="utf-8")
    return len(active_ids)


def _heartbeat_register(workspace: Path) -> int:
    """v1.9.25: register the heartbeat as verifiable state (.heartbeat.json).

    Turns 'monitoring is running' from a self-claim into a checked file state.
    Every heartbeat tick refreshes `last_tick_ts`; --heartbeat-check exits 1
    when the file is missing or stale (>35 min — covers 5-min cron + jitter).
    """
    import json as _json

    state = {"started_ts": utc_now(), "interval_min": 5, "last_tick_ts": utc_now()}
    path = workspace / "runs" / ".heartbeat.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps(state, indent=2), encoding="utf-8")
    print(f"OK: heartbeat registered at {path} (interval 5m)")
    return 0


def _heartbeat_verify(workspace: Path) -> int:
    """v1.9.25: exit 0 = monitoring IS running; exit 1 = NOT running.

    Checks <ws>/runs/.heartbeat.json exists AND last_tick_ts is < 35 min old
    (a 5-min cron tick should refresh it continuously). Missing/stale means
    the orchestrator's 'monitoring started' claim is false.
    """
    import json as _json

    path = workspace / "runs" / ".heartbeat.json"
    if not path.exists():
        print("HEARTBEAT DOWN: no .heartbeat.json — monitoring was never started", file=sys.stderr)
        return 1
    try:
        state = _json.loads(path.read_text(encoding="utf-8"))
        last = datetime.fromisoformat(state.get("last_tick_ts", "").replace("Z", "+00:00"))
    except Exception as exc:
        print(f"HEARTBEAT DOWN: .heartbeat.json unreadable ({exc})", file=sys.stderr)
        return 1
    age = datetime.now(timezone.utc) - last
    if age > timedelta(minutes=35):
        print(f"HEARTBEAT STALE: last tick {state.get('last_tick_ts')} ({int(age.total_seconds()//60)} min ago > 35)", file=sys.stderr)
        return 1
    print(f"OK: heartbeat alive (started {state.get('started_ts')}, last tick {state.get('last_tick_ts')})")
    return 0


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

    Expiry (v1.9.7): if the state carries an expires_at in the past, the
    activation is STALE and the hook is treated as inactive. A stale activation
    from a 5-day-old session must not keep firing hooks in a fresh session —
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
    """v1.9.8 — hooks use THIS, not is_active().

    is_active() defaults to True when no state file exists (legacy: an
    unconfigured workspace must not silently disable enforcement). That is the
    WRONG default for the new narrow hooks (dispatch_gate, worker_pulse):
    v1.9.7 semantics = default-INACTIVE — no activation → hooks sleep. A
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
    v1.9.25: also refreshes .heartbeat.json last_tick_ts — a renewing tick IS
    the proof the heartbeat is alive (--heartbeat-check keys off this)."""
    state = read_state(workspace)
    if not state:
        # no prior activation — activate the default set
        return update_state(workspace, "none", "IDLE", ttl_minutes=ttl_minutes)
    state["ts"] = utc_now()
    state["expires_at"] = (datetime.now(tz=timezone.utc) + timedelta(minutes=ttl_minutes)).isoformat(timespec="seconds").replace("+00:00", "Z")
    write_state(workspace, state)
    # v1.9.25: heartbeat liveness = renew ticks (only if registered)
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
                        help="v1.9.18: register kunglao-agent hooks in ~/.claude/settings.json (PreToolUse "
                             "worker_budget+dispatch_gate, PostToolUse worker_budget+worker_pulse, matcher "
                             "Agent). Idempotent: merges into existing hooks config, preserves other keys. "
                             "Called at Phase 0 by the orchestrator; fixes 'hooks never fired' recurrences.")
    parser.add_argument("--reconcile", action="store_true",
                        help="v1.9.18: rebuild [active_workers] from the GROUND TRUTH — worker status "
                             "files in every .wt-*/ worktree (last status line == in-progress). Removes "
                             "zombie entries that accumulate when PostToolUse remove_worker never fires "
                             "(hooks not wired). Call at Phase 0 and every heartbeat tick.")
    parser.add_argument("--heartbeat-on", action="store_true",
                        help="v1.9.25: REGISTER the heartbeat as a verifiable state — writes "
                             "<ws>/runs/.heartbeat.json {started_ts, interval_min, cron_id} so "
                             "'monitoring is running' is a checked file state, not a self-claim. "
                             "Call at Phase 0 right after the /loop cron is created.")
    parser.add_argument("--heartbeat-check", action="store_true",
                        help="v1.9.25: VERIFY the heartbeat is actually registered — exit 0 if "
                             "<ws>/runs/.heartbeat.json exists and is < 35 min old (cron tick should "
                             "have refreshed it); exit 1 if missing/stale = monitoring is NOT running. "
                             "Call every heartbeat tick and before declaring CONVERGED.")
    args = parser.parse_args()

    workspace = Path(args.workspace)

    if args.wire_up:
        n = _wire_up_settings()
        print(f"OK: kunglao-agent hooks wired into settings.json ({n} entries)")
        return 0

    if args.heartbeat_on:
        return _heartbeat_register(workspace)

    if args.heartbeat_check:
        return _heartbeat_verify(workspace)

    if args.reconcile:
        n = _reconcile_workers(workspace)
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