# -*- coding: utf-8 -*-
"""hook_activation.py - selective hook activation for kunglao-agent (core).

User pain point (verbatim, in Chinese): "kunglao-agent 需要安装hook，但是只有被激活的时候hook才生效，
否则会产生大量噪声给 kunglao-agent"
("kunglao-agent needs hooks installed, but they must only take effect when
activated, otherwise they generate heavy noise for kunglao-agent")

kunglao-agent has 7+ enforcement hooks (active_intervention, cost_gate,
backtrack_gate, reuse_gate, etc.). Running ALL of them on EVERY
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
  uv run --project <skill_root> <skill_root>/scripts/hook_activation.py <workspace> [--set-active h1,h2] [--set-paused h3] [--phase X]
  uv run --project <skill_root> <skill_root>/scripts/hook_activation.py <workspace> --renew          # refresh expiry (kunglao-agent Phase 0)
  uv run --project <skill_root> <skill_root>/scripts/hook_activation.py <workspace> --is-active dispatch_gate
  uv run --project <skill_root> <skill_root>/scripts/hook_activation.py <workspace> --wire-up        # register hooks in <workspace>/.claude/settings.json (PROJECT-level, #258)
  uv run --project <skill_root> <skill_root>/scripts/hook_activation.py <workspace> --heartbeat-off  # stop heartbeat after CONVERGED (issue #237)

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

Issue #410 (2026-08-17): hooks may live in EITHER project-level target —
<workspace>/.claude/settings.json (the --wire-up deployment target) or the
workspace-parent <workspace-parent>/.claude/settings.json (the external_kicker
D2 dead-session-recovery read/write target). env_check accepts both; the
target set derives from wire_up_settings.hook_deployment_targets (single
source). --wire-up still writes the workspace-level file (#258).

Issue #445 (2026-08-18): this module is THE canonical hook REGISTRATION
entry (register_hooks / --wire-up). The pre-#445 layout had three
independent writers (wire_up_settings.wire_up_settings, external_kicker.
ensure_project_hooks, kunglao-init deploy_hooks), each hand-rolling entry
construction and none self-checking — a write landing on a layer that does
not fire failed silently (the T1 zombie class). Now: wire_up_settings's
writer lives HERE (its name is a deprecated alias), external_kicker and
kunglao-init construct entries via build_hook_entry below, and every
registration runs selfcheck_registration (written location vs declared
fire layer + coverage + command shape). Mismatch FAILs: --wire-up exits 1,
init returns RC_HOOK_WIRING — never a silent OK or a WARN.
"""
from __future__ import annotations

# #534: observability lifeline — module-level emit on load.
import kunglao_log  # noqa: E402

# #534: observability lifeline — module-level emit on load.
try:
    kunglao_log.emit(ws, actor="hook_activation", action="write_blocked",
                             detail="module wired")
except NameError:
    pass

import argparse
import hashlib
import json
import shutil
import sys
from collections.abc import Collection
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOOK_STATE_FILE = ".hook_state.json"
# #597: TTL value single-sourced in liveness_policy (rationale there).
from liveness_policy import DEFAULT_TTL_MINUTES  # noqa: E402
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
    "dispatch_gate",
    "worker_pulse",
    "state_anchor",
    "completion_gate",
    "user_signal_capture",   # #868 UserPromptSubmit: user-signal capture face
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


from harness_common import utc_now_z as utc_now  # #863 Family F: single source (was a local def)


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
    is_active() keeps its legacy behavior for the old gate family.

    #613: expiry is no longer silent — the first refusal per expired window
    writes a one-shot runs/.hook-slept.json + one stderr WARNING (fail-open;
    verdict unchanged; no auto-renew)."""
    state = read_state(workspace)
    if not state:
        return False  # default-inactive: no activation, no firing
    expires = state.get("expires_at")
    if expires:
        try:
            exp = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            if datetime.now(tz=timezone.utc) > exp:
                _emit_hook_slept_once(workspace, state, exp)
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
    if hook_name in active:
        return True
    # #717: ALWAYS_ARMED hooks (completion_gate) fire on membership alone.
    # is_active_strict used to fall through to `return False` here, so a
    # state file written by any partial writer (update_state, an external
    # editor, an activation that pre-dates init's always_arm) that omitted
    # the gate from active_hooks silently slept the Stop gate — the
    # sample-incident-01 0.1.2 incident: active_hooks=["active_intervention"] and
    # the completion gate never fired once in a 4-hour run. Membership in
    # ALWAYS_ARMED_HOOKS is itself the activation record (init's always_arm
    # guarantees the entry; expiry/pause/override above still bind).
    if hook_name in ALWAYS_ARMED_HOOKS:
        return True
    return False


def _emit_hook_slept_once(workspace: Path, state: dict, exp: datetime) -> None:
    """#613: one-shot observable expiry. Writes runs/.hook-slept.json once per
    expired window (same expires_at → no rewrite) and prints one stderr
    WARNING. Fail-open: any write/parse error leaves the verdict untouched."""
    try:
        runs = workspace / "runs"
        marker = runs / ".hook-slept.json"
        if marker.exists():
            prior = json.loads(marker.read_text(encoding="utf-8"))
            if prior.get("expired_at") == state.get("expires_at"):
                return  # same window already reported
        now = datetime.now(tz=timezone.utc)
        gap_seconds = int((now - exp).total_seconds())
        record = {
            "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expired_at": state.get("expires_at"),
            "gap_seconds": gap_seconds,
            "hooks_affected": list(state.get("active_hooks", [])),
        }
        runs.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        print(
            f"WARNING: activation expired {gap_seconds // 60} min ago — hooks asleep "
            f"({len(record['hooks_affected'])} hook(s)). Re-arm: hook_activation.py {workspace} --renew",
            file=sys.stderr,
        )
    except (OSError, ValueError, TypeError):
        pass  # fail-open: observability must never change the gate verdict


def completeness_report(ws: Path) -> list:
    """#810: deployed-surface completeness — carrier dests vs disk.
    No carrier (legacy/pre-T5 workspaces) → [] (the #783 drift face owns
    that verdict); carrier with dests → every missing file is listed."""
    carrier = ws / ".claude" / "deployed-manifest.json"
    if not carrier.is_file():
        return []
    try:
        data = json.loads(carrier.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    dests = data.get("dests") or []
    if not dests:
        return []
    return [d for d in dests if not (Path(ws) / d).is_file()]


def _emit_surface_incident(ws: Path) -> None:
    """#810: activation faces emit env_incident with the missing list when
    the deployed surface is incomplete — a crippled deployment must NEVER
    fail silently (the live-run sample REJECT was exactly this)."""
    try:
        missing = completeness_report(ws)
        if not missing:
            return
        import kunglao_log  # noqa: E402 (scripts/ dir on path)
        kunglao_log.emit(
            ws, "hook_activation", "env_incident",
            detail="deployed-surface incomplete - "
                   + "; ".join(missing[:20])
                   + (f" (+{len(missing) - 20} more)" if len(missing) > 20
                      else ""),
            exit=1)
    except Exception:
        pass  # observability must never break the activation writer


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
    _emit_surface_incident(workspace)  # #810: crippled deployment never fails silently
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
    # #619: audit the transition BEFORE overwriting — who renewed, whether the
    # prior state had expired, and how long the gap was (postmortem fuel).
    # Emits into the kunglao_log event stream; .hook_state.json stays minimal.
    was_expired = False
    gap_s = 0
    prior_exp = state.get("expires_at")
    if prior_exp:
        try:
            prior_dt = datetime.fromisoformat(str(prior_exp).replace("Z", "+00:00"))
            delta = datetime.now(tz=timezone.utc) - prior_dt
            gap_s = int(delta.total_seconds())
            was_expired = delta.total_seconds() > 0
        except (ValueError, TypeError):
            was_expired = False
    try:
        import kunglao_log  # noqa: E402 (scripts/ dir on path)
        kunglao_log.emit(workspace, "orchestrator", "renew",
                         detail=f"was_expired={str(was_expired).lower()};"
                                f"expiry_gap_s={gap_s};ttl_min={ttl_minutes}")
    except Exception:
        pass  # audit is observability — never fails the renew
    state["ts"] = utc_now()
    state["expires_at"] = (datetime.now(tz=timezone.utc) + timedelta(minutes=ttl_minutes)).isoformat(timespec="seconds").replace("+00:00", "Z")
    write_state(workspace, state)
    _emit_surface_incident(workspace)  # #810: renew face — same completeness guard
    # heartbeat liveness = renew ticks (only if registered)
    hb = workspace / "runs" / ".heartbeat.json"
    if hb.exists():
        try:
            import json as _json
            from heartbeat import append_tick, append_tick_log  # noqa: E402 (#754 shared writer)
            hstate = _json.loads(hb.read_text(encoding="utf-8"))
            # #754 E2: a renew IS a tick — appending keeps the continuous-tick
            # history fed from the same place last_tick_ts is refreshed (cron
            # ticks via heartbeat_tick step 6 and dispatch auto-renews alike).
            hstate["last_tick_ts"] = utc_now()
            hstate = append_tick(hstate)
            hb.write_text(_json.dumps(hstate, indent=2), encoding="utf-8")
            # #830: a renew tick lands in the durable sidecar as well.
            append_tick_log(workspace, "renew")
        except Exception:
            pass  # heartbeat file corrupt — --heartbeat-check will report it
    return state


# ===========================================================================
# #461: dispatch linkage — the dispatch event as a LIFECYCLE event
# ===========================================================================
# The enforcement pair a dispatch path depends on: the gate that observes
# the dispatch itself (dispatch_gate) and the one that observes the worker
# completing it (worker_pulse). A passing dispatch must leave both armed.
DISPATCH_HOOKS = ("dispatch_gate", "worker_pulse")


def dispatch_linkage(workspace: Path,
                     ttl_minutes: int = DEFAULT_TTL_MINUTES) -> dict:
    """#461: one call, four lifecycle effects — invoked by
    hooks/worker_budget.pre_check AFTER every gate passes (the PreToolUse
    approval point). Reuses the existing primitives only (update_state /
    write_state / renew) — no new activation mechanism, no fourth liveness
    representation (#446 F-class red line):

      1. renew        — refresh expires_at (the auto `--renew`: the 30-min
                        TTL no longer depends on the orchestrator
                        remembering; issue: "30min 过期的 --renew 由派发
                        事件自动触发")
      2. complete     — dispatch_gate + worker_pulse enter active_hooks and
                        leave paused_hooks; user_override "off" still wins
                        (an explicit operator opt-out is never force-armed)
      3. flip phase   — phase=DISPATCH, the state machine's vocabulary for
                        the issue's "IDLE→RUNNING" (workers in flight while
                        the state said IDLE was the 2026-08-18 field report)
      4. heartbeat    — renew()'s existing side effect: last_tick_ts refresh
                        (a dispatching orchestrator IS alive)

    Cold state (no .hook_state.json — the 2026-08-18 field state, 2/10
    hooks): update_state bootstraps the full tier-"none" set first.
    Returns the renewed state dict.
    """
    state = read_state(workspace)
    if not state:
        state = update_state(workspace, "none", "IDLE",
                             ttl_minutes=ttl_minutes)
    overrides = state.get("user_override", {})
    active = list(state.get("active_hooks", []))
    for hook in DISPATCH_HOOKS:
        if overrides.get(hook) == "off":
            continue  # explicit user off — never force-activate
        if hook not in active:
            active.append(hook)
    linked = dict(state)
    linked["active_hooks"] = active
    linked["paused_hooks"] = [h for h in state.get("paused_hooks", [])
                              if h not in DISPATCH_HOOKS
                              or overrides.get(h) == "off"]
    linked["phase"] = "DISPATCH"
    write_state(workspace, linked)
    # renew re-reads from disk: stamps the fresh TTL + heartbeat tick
    return renew(workspace, ttl_minutes=ttl_minutes)



# The Stop gate (completion_gate) must be ALWAYS armed — it fires on EVERY
# session termination, not just on a dispatch event. Unlike DISPATCH_HOOKS which
# are activated on each dispatch and decay, completion_gate is a permanent
# sentinel: it checks convergence_state on Stop regardless of whether any
# dispatch occurred. F-S1/#533: "init 即武装 completion_gate".
ALWAYS_ARMED_HOOKS = ("completion_gate",)


def always_arm(workspace: Path,
               ttl_minutes: int = DEFAULT_TTL_MINUTES) -> dict:
    """#533 F-S1: ensure ALWAYS_ARMED_HOOKS are in active_hooks.
    Unlike dispatch_linkage (which also flips phase=DISPATCH), this function
    only ensures the Stop gate is permanently armed. Call from init Phase 0.
    Repeated calls are idempotent."""
    state = read_state(workspace)
    if not state:
        state = update_state(workspace, "none", "IDLE", ttl_minutes=ttl_minutes)
    overrides = state.get("user_override", {})
    active = list(state.get("active_hooks", []))
    for hook in ALWAYS_ARMED_HOOKS:
        if overrides.get(hook) == "off":
            continue  # explicit user off — respect it
        if hook not in active:
            active.append(hook)
    linked = dict(state)
    linked["active_hooks"] = active
    # completion_gate is NOT paused when DISPATCH_HOOKS are unpaused
    linked["paused_hooks"] = [h for h in state.get("paused_hooks", [])
                               if h not in ALWAYS_ARMED_HOOKS
                               or overrides.get(h) == "off"]
    write_state(workspace, linked)
    return renew(workspace, ttl_minutes=ttl_minutes)

# ===========================================================================
# #445: THE canonical hook registration entry
# ===========================================================================
# Machine-readable declarations — pinned by tests/test_hook_registration_entry.py.
# Exactly one registration entry exists; the kicker's bootstrap writer is a
# declared subordinate. (#863: the pre-#445 deprecated alias retired —
# DEPRECATED_ALIASES is empty.) Anything else writing hook entries is an
# unregistered fourth path and fails the single-entry scan.
CANONICAL_REGISTRATION_ENTRY = "hook_activation.register_hooks"
DEPRECATED_ALIASES: tuple = ()
DECLARED_SUBORDINATE_WRITERS = (
    # dead-session bootstrap subset, workspace-parent target — see
    # external_kicker.REGISTRATION_RELATION for the full contract.
    "external_kicker.ensure_project_hooks",
)


class HookWiringSelfcheckError(RuntimeError):
    """#445: post-registration self-check failed — the hooks were NOT
    verifiably registered on a layer that fires. Raised by register_hooks
    (fail-closed); the CLI maps it to exit 1, init to RC_HOOK_WIRING."""


def build_hook_entry(hook_dir: Path, hook_file: str,
                    matcher: str | None = None,
                    *, project: Path | None = None) -> dict:
    """THE hook-entry construction source (#445) — every writer derives its
    entries from this one function (pre-#445: three hand-rolled copies).
    matcher=None -> a Stop-style entry (no matcher key: Stop hooks fire on
    every termination, not on a tool matcher).

    POSIX path (forward slashes): hooks run via `sh -c` — Windows backslash
    paths get their backslashes eaten as escape chars (C:\\Users\\... ->
    C:Users...). #389: hooks run via `uv run --project <skill_root>` — bare
    python can resolve to 2.x and kill every registered hook; uv uses the
    skill's own project venv (python 3.11+).
    """
    # #783: deployed copies run under the WORKSPACE project root so an
    # upgrade of the skill package never mutates existing workspaces;
    # legacy (undeployed) callers fall back to the installing skill dir.
    project_root = Path(project).resolve() if project else Path(hook_dir).parent
    p = (Path(hook_dir) / hook_file).as_posix()
    # #811: hooks inherit the invoking shell's locale — a GBK console turns
    # every encoding-less IO in the hook into a decode bomb. PYTHONUTF8=1
    # (PEP 540) pins UTF-8 for the whole subprocess tree, covering legacy
    # call sites before the #811 explicit-encoding sweep reaches them.
    hooks = [{"type": "command",
              "command": (f"PYTHONUTF8=1 "
                          f"uv run --project {project_root.as_posix()} {p}")}]
    if matcher is None:
        return {"hooks": hooks}
    return {"matcher": matcher, "hooks": hooks}


def canonical_install_root() -> Path:
    """THE executing install's skill root — where hook COMMAND paths must
    point (#752).

    Issue #269 modeled only two states (canonical vs worktree), so a dev
    run from a LONG-LIVED co-install (`~/.claude/skills/kunglao-agent-dev`)
    teleported every wire-up command back at the stale production install.
    User ruling (2026-08-27): a dev install under ~/.claude/skills/ is a
    durable install, NOT a worktree. Three states, one predicate:

      durable    — this module executes from ANY <HOME>/.claude/skills/
                   <name>/ package (production OR dev co-install OR an
                   arbitrarily renamed install): THAT root wins;
      ephemeral  — anything else (repo checkout, <HOME>/.claude/.wt-*/
                   worktree): falls back to the canonical production
                   install ~/.claude/skills/kunglao-agent — binding hook
                   commands to the checkout dies with it (#228).

    Both sides are resolved so macOS /var -> /private/var symlink spellings
    compare equal. Reads Path.home() (never env vars) so test fake-homes
    bind through the established monkeypatch seam.
    """
    here_pkg = Path(__file__).resolve().parent.parent
    skills_root = (Path.home() / ".claude" / "skills").resolve()
    if here_pkg.parent.resolve() == skills_root:
        return here_pkg
    return skills_root / "kunglao-agent"


def _canonical_hooks_dir() -> Path:
    """Canonical deployed skill hooks dir (#752 re-statement of #269):
    `canonical_install_root() / "hooks"` — see that function for the
    durable-vs-ephemeral ruling."""
    return canonical_install_root() / "hooks"


def _resolve_registration_target(workspace: Path | None,
                                 global_opt_in: bool = False) -> Path:
    """Resolve the settings.json this registration writes (#445 seam —
    tests inject the historical mis-wiring here to prove FAIL semantics).

      - global_opt_in=True -> Path.home()/.claude/settings.json — EXPLICIT
        opt-in only (the pre-#258 default wrote the user-global settings and
        bound hooks to paths that died with the worktree);
      - workspace given    -> <workspace>/.claude/settings.json (#258);
      - workspace None     -> <cwd>/.claude/settings.json (cwd probe).
    """
    if global_opt_in:
        return Path.home() / ".claude" / "settings.json"
    if workspace is not None:
        return Path(workspace).resolve() / ".claude" / "settings.json"
    return Path.cwd().resolve() / ".claude" / "settings.json"


_SELFCHECK_LAYERS = ("project", "user-opt-in", "operator-declared")


def selfcheck_registration(target: Path, *, expected_files: Collection[str],
                           hook_dir: Path | None = None,
                           workspace: Path | None = None,
                           layer: str = "project",
                           deployed_project: Path | None = None) -> dict:
    """#445 post-registration self-check — the written-location vs
    actual-fire-layer assertion, run AFTER every registration write.

    Re-reads the WRITTEN FILE from disk (maker-checker: never trust the
    in-memory dict the writer just assembled) and asserts three legs:

      layer    — `layer="project"`: the resolved target must be a member of
                 wire_up_settings.hook_deployment_targets(workspace) AND not
                 the user-global ~/.claude/settings.json (a write outside the
                 declared fire layers is the historical "repaired the wrong
                 file" bug). `layer="user-opt-in"`: must BE the user-global
                 file. `layer="operator-declared"`: an explicitly named
                 operator target (--hooks-json) — legs below still apply.
      coverage — every expected hook file appears as a command basename in
                 the re-read file (Pre/Post/Stop all scanned) — the v1.9.37
                 "settings rewrite dropped the hooks segment" class.
      shape    — every expected command is uv-form pointing into the
                 EXECUTING install's hooks dir, derived independently here
                 via _canonical_hooks_dir (#752 D4+: the legacy hook_dir
                 parameter is accepted but ignored for the verdict) — the
                 #269 worktree-bound-command silent-death class plus the
                 #752 self-certifying-variable class.
                 Path existence is deliberately NOT asserted (a canonical
                 install under a test HOME is a legitimate shape).

    Pure checker: returns {"ok", "layer", "target", "mismatches",
    "present", "missing"} and never raises — the CALLER decides the failure
    mode (register_hooks raises HookWiringSelfcheckError; init maps to
    RC_HOOK_WIRING; the CLI prints FAIL and exits 1).
    """
    if layer not in _SELFCHECK_LAYERS:
        raise ValueError(f"unknown self-check layer {layer!r}; "
                         f"valid: {_SELFCHECK_LAYERS}")
    import wire_up_settings  # lazy: registry single source (#372/#410)

    def _bad(reason: str) -> dict:
        return {"ok": False, "layer": layer, "target": str(target),
                "mismatches": [reason], "present": [],
                "missing": sorted(expected_files)}

    if not Path(target).exists():
        return _bad(f"written file absent: {target}")
    try:
        settings = json.loads(Path(target).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return _bad(f"written file unparseable: {exc}")

    cmds = [str(h.get("command", ""))
            for entries in (settings.get("hooks") or {}).values()
            for e in entries
            for h in e.get("hooks", [])]
    bases = {c.replace("\\", "/").rsplit("/", 1)[-1] for c in cmds}
    expected = set(expected_files)
    missing = sorted(expected - bases)
    present = sorted(expected & bases)
    mismatches: list[str] = []
    # #810: shape contract — pseudo-event keys ("Agent"/"Bash" promoted into
    # the key slot) are the bug shape; assert the canonical form the writer
    # emits and every event-keyed checker reads.
    mismatches.extend(
        "shape: " + s for s in
        wire_up_settings.registration_shape_issues(settings))
    if missing:
        mismatches.append(
            f"coverage: hook entries missing from written file: {missing}")

    t = Path(target).resolve()
    user_global = (Path.home() / ".claude" / "settings.json").resolve()
    if layer == "user-opt-in":
        if t != user_global:
            mismatches.append(
                f"layer: user-opt-in registration must write the user-global "
                f"file, wrote {t}")
    elif layer == "project":
        fire = {p.resolve() for p in
                wire_up_settings.hook_deployment_targets(
                    workspace if workspace is not None else Path.cwd())}
        if t not in fire:
            mismatches.append(
                f"layer: written file {t} is not a declared hook fire layer "
                f"for this workspace (fire layers: {sorted(map(str, fire))})")
        elif t == user_global:
            mismatches.append(
                "layer: user-global settings is not a project fire layer "
                "(#258/#445 mis-wiring class)")

    # #752 D4+: the shape expectation is recomputed HERE from the executing
    # install (_canonical_hooks_dir) — never taken from a caller variable.
    # The legacy hook_dir parameter stays ACCEPTED for API compatibility
    # (#445 callers may still pass it) but feeds nothing: a checker handed
    # the same wrong dir the writer wrote ("write whatever, verify
    # whatever") must fail, not certify itself. Path existence is
    # deliberately NOT asserted (a canonical install under a test HOME is a
    # legitimate shape).
    # #783: in deploy mode the executing authority is the WORKSPACE copy —
    # the declared mode comes from the registration contract (deployed_project),
    # so a checker handed the same wrong mode still fails; bare-skill fallback
    # recomputes from the executing install as before.
    if deployed_project is not None:
        d = deployed_project.resolve() / ".claude" / "hooks"
        prefix = f"uv run --project {deployed_project.resolve().as_posix()} "
    else:
        d = _canonical_hooks_dir()
        prefix = f"uv run --project {d.parent.as_posix()} "
    for c in cmds:
        base = c.replace("\\", "/").rsplit("/", 1)[-1]
        if base not in expected:
            continue  # unrelated entries are not this registration's claim
        # #811: entries carry an optional PYTHONUTF8=1 env prefix (PEP 540
        # injection from build_hook_entry) — strip it before the shape check.
        body = c[len("PYTHONUTF8=1 "):] if c.startswith("PYTHONUTF8=1 ") else c
        if not (body.startswith(prefix)
                and body[len(prefix):].startswith(d.as_posix() + "/")):
            mismatches.append(
                f"shape: command for {base} is not canonical (must be "
                f"uv-form into the declared hooks dir {d}): {c}")

    return {"ok": not mismatches, "layer": layer, "target": str(target),
            "mismatches": mismatches, "present": present, "missing": missing}


def verify_install_references(workspace: Path,
                              active_root: Path | None = None) -> dict:
    """#752 D5 residual-scavenger verifier — does any framework carrier of
    this workspace still reference an install OTHER than the executing one?

    Delegates the scan to install_reference.scan_workspace over the two
    carriers (.claude/settings.json, CLAUDE.md). Pure check: returns

        {"ok": <no stale refs>, "active_root": "<root>",
         "stale": {carrier: [ref, ...]}, "stale_total": <n>}

    and never raises for absent carriers. Rewiring is rewire_workspace's
    job (exercised by kunglao_upgrade's end-step sweep); this stays
    read-only so callers can gate on it without side effects.
    """
    import install_reference  # lazy: scripts/ sibling (#752 one-way dep)
    root = Path(active_root) if active_root is not None \
        else canonical_install_root()
    stale = install_reference.scan_workspace(workspace, root)
    total = sum(len(v) for v in stale.values())
    return {"ok": total == 0, "active_root": str(root),
            "stale": stale, "stale_total": total}


def deploy_workspace_copy(ws: Path) -> dict:
    """#783: materialize the deployment manifest into <ws>/.claude/.

    Copies every manifest file (hooks/agents/scaffold closure) into the
    workspace, overwriting stale copies (D3: overwrite + WARN detail);
    identical-sha targets are skipped idempotently. Returns a report dict
    {copied, skipped, entries, touched, digest}. Fail-loud on unreadable
    manifest — a silently empty deployment would unregister the gates.

    #783 T5: the deployment leaves the digest CARRIER
    (<ws>/.claude/deployed-manifest.json) behind — the check-stale third
    criterion and upgrade's refresh both key off it. The digest is the
    build_entries() recomputation (the skill-side truth), not the yaml
    bytes, so a green-repo deploy and a refresh carrier always agree
    (design: deploy_manifest is the single digest authority)."""
    from deploy_manifest import (MANIFEST as _MF, build_entries as _build,
                                 write_carrier)

    if not _MF.is_file():
        raise RuntimeError(f"deployment manifest missing: {_MF}")
    import yaml as _yaml
    data = _yaml.safe_load(_MF.read_text(encoding="utf-8")) or {}
    ws = ws.resolve()
    copied = skipped = 0
    touched: list[str] = []
    for e in data.get("files") or []:
        src = Path(__file__).resolve().parent.parent / str(e["src"])
        dst = ws / str(e["dest"])
        if not src.is_file():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.is_file() and hashlib.sha256(dst.read_bytes()).hexdigest() == e.get("sha256"):
            skipped += 1
            continue
        shutil.copy2(src, dst)
        copied += 1
        touched.append(str(e["dest"]))
    entries = _build()
    carrier = write_carrier(ws, entries)
    return {"copied": copied, "skipped": skipped,
            "entries": len(data.get("files") or []),
            "touched": touched, "digest": carrier["deployed_digest"],
            "carrier": carrier}



# #810 correction (audit B5 CONFIRMED): deployed-mode registration MUST emit
# the same canonical event-keyed shape as register_hooks — matcher lives
# under `matcher`, NEVER promoted into the event-key slot ("Agent"/"Bash"
# are not Claude Code event names; the old shape made env_check blind while
# both selfchecks passed — three checkers, three answers).
# #601: MCP host-channel matcher — main-agent direct calls to the three
# VM-only dynamic-analysis namespaces ride the SAME orchestrator_tool_guard
# hook file (second PreToolUse entry; workers inside .wt-* pass in-script).
# Double-registration bookkeeping: wire_up_settings.DOUBLE_REGISTERED_HOOKS.
ORCHESTRATOR_MCP_MATCHER = (
    "mcp__ghidra__.*|mcp__x64dbg__.*|mcp__frida__.*")

_DEPLOYED_WIRING = (
    # (event, matcher, hook_file) — mirrors register_hooks exactly.
    ("PreToolUse", "Agent", "env_check_gate.py"),
    ("PreToolUse", "Agent", "worker_budget.py"),
    ("PreToolUse", "Agent", "dispatch_gate.py"),
    ("PreToolUse", "Agent", "recall_inject.py"),
    ("PreToolUse", "Bash", "heartbeat_touch.py"),
    ("PreToolUse", "Bash", "orchestrator_tool_guard.py"),
    ("PreToolUse", ORCHESTRATOR_MCP_MATCHER, "orchestrator_tool_guard.py"),  # #601
    ("PreToolUse", "Edit|Write|MultiEdit", "write_guard.py"),
    ("PostToolUse", "Agent", "worker_budget.py"),   # #675 double registration
    ("PostToolUse", "Agent", "worker_pulse.py"),
    ("PostToolUse", "Agent", "state_anchor.py"),
    ("PostToolUse", "Bash", "violation_capture.py"),
    ("PostToolUse", "Bash", "bash_fact_guard.py"),  # #809 Post wiring
    ("PostToolUse", "Edit|Write|MultiEdit|Agent",
     "cost_input_capture.py"),  # #873 cost 输入捕获
    ("Stop", "", "completion_gate.py"),
)


def register_hooks_deployed(ws: Path) -> int:
    """#783 opt-in inverted deployment: workspace-local hooks + registration.

    Copies the deployment manifest into <ws>/.claude/, then registers the
    canonical WIRE_UP registry against those LOCAL copies with
    `uv run --project <workspace>` commands. #810: entries are keyed by
    canonical event names with matcher under `matcher` — identical shape to
    register_hooks, so env_check and both selfchecks read the same truth.
    Idempotent per (event, matcher, command-basename)."""
    report = deploy_workspace_copy(ws)
    print(f"OK: deployed framework files (copied={report['copied']}, "
          f"unchanged={report['skipped']})")
    ws = Path(ws).resolve()
    hooks_dir = ws / ".claude" / "hooks"
    settings_path = ws / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    existing = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    hooks = existing.setdefault("hooks", {})

    def _basename_used(event: str, matcher: str, hf: str) -> bool:
        for e in hooks.get(event) or []:
            if matcher and e.get("matcher") != matcher:
                continue
            for h in e.get("hooks", []):
                cmd = str(h.get("command", "")).replace("\\", "/")
                if cmd.rsplit("/", 1)[-1] == hf:
                    return True
        return False

    added = 0
    for event, matcher, hf in _DEPLOYED_WIRING:
        if _basename_used(event, matcher, hf):
            continue
        bucket = hooks.get(event) or []
        bucket.append(build_hook_entry(hooks_dir, hf, matcher or None,
                                       project=ws))
        hooks[event] = bucket
        added += 1

    # #618: heartbeat_touch rides a second slot — Stop. The session's last
    # beat per turn must land even when no Bash tool ran (pure Read/Grep
    # analysis stretches would otherwise leave the durable sidecar cold).
    # Mirrors worker_budget's double-registration shape.
    hb = "heartbeat_touch.py"
    if not _basename_used("Stop", "", hb):
        stop_bucket = hooks.get("Stop") or []
        stop_bucket.append(build_hook_entry(hooks_dir, hb, None, project=ws))
        hooks["Stop"] = stop_bucket
        added += 1

    settings_path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False),
        encoding="utf-8")

    check = selfcheck_registration(
        settings_path,
        expected_files=_wire_up_hook_files(),
        workspace=ws,
        layer="project",
        deployed_project=ws)
    if not check["ok"]:
        raise HookWiringSelfcheckError(
            f"{settings_path} failed the deployed-mode self-check "
            f"({', '.join(check['mismatches'])})")
    print(f"OK: registered {added} deployed hook entries")
    return 0

def resolve_deployment(ws: Path | None):
    """#783 phase-2 inversion selector.

    Returns (hook_dir, project). When the workspace carries .claude/hooks
    (the manifest was materialized there), commands are rewritten to those
    WORKSPACE-LOCAL copies with the workspace as the uv project root -- this
    is what makes an initialized workspace self-contained against later
    skill-package upgrades. Otherwise falls back to the canonical install
    dir with no project override."""
    if ws is None:
        return _canonical_hooks_dir(), None
    w = Path(ws).resolve()
    local = w / ".claude" / "hooks"
    if local.is_dir():
        return local, w
    return _canonical_hooks_dir(), None


def register_hooks(workspace: Path | None = None,
                   global_opt_in: bool = False) -> int:
    """THE registration writer (#445) — register kunglao-agent hooks in the
    PROJECT-level settings.json. Moved verbatim from wire_up_settings
    (pre-#445 name: wire_up_settings.wire_up_settings).

    Deployment target (#258): <workspace>/.claude/settings.json (cwd probe
    when workspace is None); global_opt_in=True is the EXPLICIT user-global
    escape hatch. Idempotent merge: reads current settings, appends our hook
    entries (PreToolUse/Agent + PostToolUse/Agent + heartbeat_touch on Bash
    + completion_gate on Stop), skips entries that already exist (same
    basename), preserves every other key. Writes back with 2-space indent.

    #445: after writing, runs selfcheck_registration and RAISES
    HookWiringSelfcheckError on any mismatch (wrong layer / dropped
    entries / non-canonical commands) — fail-closed, never a silent OK.
    Returns the number of hook entries registered.
    """
    settings_path = _resolve_registration_target(workspace, global_opt_in)
    if global_opt_in:
        print(f"WARNING: wiring kunglao-agent hooks into the USER-GLOBAL "
              f"{settings_path} — hooks must live in the project-level "
              f".claude/settings.json; global deployment is "
              f"explicit opt-in ONLY.", file=sys.stderr)

    existing = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    hooks = existing.get("hooks") or {}
    pre = hooks.get("PreToolUse") or []
    post = hooks.get("PostToolUse") or []

    # hook_dir resolution (#783 phase-2): workspace-local copies win when
    # materialized; canonical install dir otherwise (legacy + global path).
    hook_dir, project_ws = resolve_deployment(
        workspace if not global_opt_in else None)

    def _ensure(entries: list, matcher: str, hook_file: str) -> tuple[list, bool]:
        new = [e for e in entries if e.get("matcher") == matcher]
        other = [e for e in entries if e.get("matcher") != matcher]
        # remove legacy entries with the same basename (backslash paths from
        # pre-posix wire-up) so re-wiring replaces them, not stacks.
        new = [
            e for e in new
            if not any((h.get("command", "").replace("\\", "/").rsplit("/", 1)[-1] == hook_file) for h in e.get("hooks", []))
        ]
        new.append(build_hook_entry(hook_dir, hook_file, matcher,
                                    project=project_ws))
        return other + new, True

    def _ensure_stop(entries: list, hook_file: str) -> tuple[list, bool]:
        """Stop hooks carry no matcher (they fire on every Stop event). Dedupe
        by command basename across all Stop entries so re-wiring replaces, not
        stacks. Appends one entry with the single hook."""
        kept = []
        for e in entries:
            hs = e.get("hooks", [])
            filtered = []
            for h in hs:
                cmd = str(h.get("command", "")).replace("\\", "/")
                if cmd.rsplit("/", 1)[-1] == hook_file:
                    continue  # drop existing — re-added fresh below
                filtered.append(h)
            if filtered:
                kept.append({"hooks": filtered})
        kept.append(build_hook_entry(hook_dir, hook_file, None,
                                     project=project_ws))
        return kept, True

    count = 0
    # env_check_gate FIRST: the environment hard-gate (#233) must reject a
    # teammate-polluted dispatch before any budget/state logic runs.
    pre, added = _ensure(pre, "Agent", "env_check_gate.py")
    count += added
    pre, added = _ensure(pre, "Agent", "worker_budget.py")
    count += added
    pre, added = _ensure(pre, "Agent", "dispatch_gate.py")
    count += added
    # recall_inject (#268): runtime knowledge recall injected into every claim
    # dispatch. Inject-only (always exits 0 — recall must never block dispatch)
    # and deliberately NOT activation-gated: knowledge helps whether or not the
    # enforcement hooks are activated. Grouped with the dispatch injectors.
    pre, added = _ensure(pre, "Agent", "recall_inject.py")
    count += added
    # heartbeat_touch on matcher=Bash — ANY tool activity refreshes
    # last_tick_ts, decoupling heartbeat liveness from orchestrator cognition.
    pre, added = _ensure(pre, "Bash", "heartbeat_touch.py")
    count += added
    # orchestrator_tool_guard (#608): PreToolUse/Bash WARN on analysis
    # binaries outside .wt-* worktrees (maker-checker, target-based
    # #532-style). The #608 landing added the hook file + the registry
    # entry + the self-check expectation but missed THIS writer call —
    # the self-check then failed every wire-up with "missing
    # ['orchestrator_tool_guard.py']" (the CI regression fixed here).
    pre, added = _ensure(pre, "Bash", "orchestrator_tool_guard.py")
    count += added
    # #601: same hook file, second matcher — MCP host-channel REJECT face
    # (mcp__ghidra__* / mcp__x64dbg__* / mcp__frida__* for the MAIN agent;
    # workers pass in-script via the .wt-* arming check). Structural second
    # registration of orchestrator_tool_guard.py — pinned by
    # wire_up_settings.DOUBLE_REGISTERED_HOOKS.
    pre, added = _ensure(pre, ORCHESTRATOR_MCP_MATCHER,
                         "orchestrator_tool_guard.py")
    count += added
    # write_guard (#532): the four-carrier write gate on the Edit/Write face.
    # NOT activation-gated by design (its docstring records why: the failure
    # mode it exists to stop is "nobody dispatched, so nothing was armed") —
    # arming is target-based (path is a contract carrier), not TTL-based.
    pre, added = _ensure(pre, "Edit|Write|MultiEdit", "write_guard.py")
    count += added
    # #675: this double registration (worker_budget Pre+Post) is pinned by
    # wire_up_settings.DOUBLE_REGISTERED_HOOKS — test count anchors derive
    # from it; changing the double-registration structure updates BOTH.
    post, added = _ensure(post, "Agent", "worker_budget.py")
    count += added
    post, added = _ensure(post, "Agent", "worker_pulse.py")
    count += added
    # state_anchor (#44): per-turn mechanical state re-anchor on every worker
    # completion — the L1 PREVENT layer (F5 forget/refresh).
    post, added = _ensure(post, "Agent", "state_anchor.py")
    count += added
    # violation_capture (#718): PostToolUse/Bash mechanical recorder —
    # out-of-band sed rewrites of contract-carrier fields (the write_guard
    # bypass) + python tracebacks in tool output. RECORDER, never blocks:
    # exit 0 forever, events only. Posture mirrors heartbeat_touch (Bash
    # matcher, fail-open) with the WARN-record semantics of #608.
    post, added = _ensure(post, "Bash", "violation_capture.py")
    count += added
    # bash_fact_guard (#809): PostToolUse/Bash facts-写入纳管面——命令命中
    # facts/*.md 且文件已落盘时逐文件 lint，违规落账 + additionalContext
    # 响亮提示。RECORDER+signal 姿态（fail-open，永不打断 Bash）；裁决权
    # 仍在 write_guard 的结构门，本 face 负责"盲区不再无声"。
    post, added = _ensure(post, "Bash", "bash_fact_guard.py")
    count += added

    # completion_gate (#55): the code-owned completion gate. Stop hook — fires
    # at session termination, blocks when task-oracle.yaml is unsatisfied.
    # No matcher (Stop is not a tool-use event); dedupe by command basename.
    stop = hooks.get("Stop") or []
    stop, added = _ensure_stop(stop, "completion_gate.py")
    count += added

    hooks["PreToolUse"] = pre
    hooks["PostToolUse"] = post
    hooks["Stop"] = stop
    existing["hooks"] = hooks
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # #445: written ≠ fired until verified — self-check re-reads the file.
    # #752 D4+: no hook_dir forwarding — the checker derives its own
    # expectation from the executing install (writer/checker separation).
    check = selfcheck_registration(
        settings_path,
        expected_files=_wire_up_hook_files(),
        workspace=workspace,
        layer="user-opt-in" if global_opt_in else "project",
        deployed_project=project_ws)
    if not check["ok"]:
        raise HookWiringSelfcheckError(
            f"{settings_path} failed the post-registration self-check "
            f"({', '.join(check['mismatches'])}) — the hooks are NOT "
            f"verifiably registered on a layer that fires (#445)")
    return count


def _wire_up_hook_files() -> frozenset[str]:
    """Registry accessor (lazy import — the registry's home is
    wire_up_settings, unchanged by #445)."""
    import wire_up_settings
    return wire_up_settings.WIRE_UP_HOOK_FILES


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
                             "(project-level; NOT global — issue: the pre-issue- default wrote "
                             "the user-global settings, binding hooks to a worktree path that dies "
                             "with the worktree). Idempotent: merges into existing hooks config, "
                             "preserves other keys. Called at Phase 0 by the orchestrator; fixes "
                             "'hooks never fired' recurrences.")
    parser.add_argument("--deploy-local", action="store_true",
                        help="#783 opt-in inverted deployment: copy the "
                             "deployment manifest into <workspace>/.claude/ "
                             "(hooks + agents + scaffold closure) and "
                             "register the canonical registry against those "
                             "WORKSPACE-LOCAL copies (uv project = workspace). "
                             "Makes the workspace self-contained against later "
                             "skill-package upgrades.")
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
    parser.add_argument("--loop-registered", action="store_true",
                        help="mark the cron loop registration "
                             "(loop_registered=true in <ws>/runs/.heartbeat.json). "
                             "Passed by the heartbeat loop prompt's FIRST action — "
                             "the prompt body executing is the proof CronCreate "
                             "accepted it. Combine with --heartbeat-on (register + "
                             "mark in one call); alone it marks an existing file. "
                             "heartbeat_loop_prompt.py --verify HARD-fails while the "
                             "marker is false (silent cron-registration failure is "
                             "forbidden).")
    parser.add_argument("--heartbeat-check", action="store_true",
                        help="VERIFY the heartbeat is actually registered — exit 0 if "
                             "<ws>/runs/.heartbeat.json exists and is < 35 min old (cron tick should "
                             "have refreshed it); exit 1 if missing/stale = monitoring is NOT running. "
                             "Call every heartbeat tick and before declaring CONVERGED.")
    parser.add_argument("--heartbeat-off", action="store_true",
                        help="STOP the heartbeat (converged teardown dual-constraint) — "
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
    if args.deploy_local:
        return register_hooks_deployed(Path(args.workspace).resolve())
    if args.wire_up:
        # #445: THE canonical registration entry. Post-write self-check is
        # part of the registration itself — a wiring that lands on a layer
        # that does not fire FAILS here (exit 1), so init (skills/init runs
        # exactly this command) fails loudly instead of reporting OK.
        target = _resolve_registration_target(workspace, global_opt_in=False)
        try:
            n = register_hooks(workspace=workspace)
        except HookWiringSelfcheckError as exc:
            print(f"FAIL: hook wiring selfcheck — {exc}", file=sys.stderr)
            return 1
        print(f"OK: kunglao-agent hooks wired into {target} ({n} entries) "
              f"+ selfcheck PASS (layer=project)")
        # #454: wiring != activation — the wired line must never read as
        # armed. Wired hooks are DORMANT by design (v1.9.7 default-inactive:
        # no .hook_state.json -> hooks sleep); activation is orchestrator-
        # owned (Phase 0) and short-lived (TTL renewed by --renew).
        print(f"NOTE: hooks wired but dormant - activation is orchestrator-"
              f"owned (Phase 0, --tier/--set-active) with a "
              f"{DEFAULT_TTL_MINUTES}-min TTL renewed by --renew; "
              f"no .hook_state.json -> hooks sleep")
        return 0

    if args.heartbeat_on:
        from heartbeat import heartbeat_register, mark_loop_registered
        rc = heartbeat_register(workspace,
                                loop_registered=args.loop_registered)
        if rc == 0 and args.loop_registered:
            rc = mark_loop_registered(workspace)
        return rc

    if args.loop_registered:
        from heartbeat import mark_loop_registered
        return mark_loop_registered(workspace)

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
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
