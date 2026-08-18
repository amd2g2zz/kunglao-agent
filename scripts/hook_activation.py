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

import argparse
import json
import sys
import warnings
from collections.abc import Collection
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


# ===========================================================================
# #445: THE canonical hook registration entry
# ===========================================================================
# Machine-readable declarations — pinned by tests/test_hook_registration_entry.py.
# Exactly one registration entry exists; legacy names survive as declared
# aliases (deprecated, #446 retires them) and the kicker's bootstrap writer
# as a declared subordinate. Anything else writing hook entries is an
# unregistered fourth path and fails the single-entry scan.
CANONICAL_REGISTRATION_ENTRY = "hook_activation.register_hooks"
DEPRECATED_ALIASES = (
    "wire_up_settings.wire_up_settings",  # pre-#445 full-registry writer
)
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
                     matcher: str | None) -> dict:
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
    skill_root = Path(hook_dir).parent
    p = (Path(hook_dir) / hook_file).as_posix()
    hooks = [{"type": "command",
              "command": f"uv run --project {skill_root.as_posix()} {p}"}]
    if matcher is None:
        return {"hooks": hooks}
    return {"matcher": matcher, "hooks": hooks}


def _canonical_hooks_dir() -> Path:
    """Canonical deployed skill hooks dir — where hook COMMAND paths must point.

    Issue #269: hook commands are absolute paths into the CANONICAL skill
    install (~/.claude/skills/kunglao-agent/hooks), never this module's own
    location. This script may be run from a dev worktree (<HOME>/.claude/
    .wt-*/); a worktree-bound command dies with the worktree — the #228
    incident: 8 hooks went silent at once when the referenced path was
    deleted. When this module IS deployed at the canonical location (the
    normal production case), the two coincide and `here` wins.
    """
    here = Path(__file__).resolve().parent.parent / "hooks"
    canonical = Path.home() / ".claude" / "skills" / "kunglao-agent" / "hooks"
    return here if here == canonical else canonical


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
                           layer: str = "project") -> dict:
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
                 declared hook_dir (default: the canonical deployed skill
                 dir) — the #269 worktree-bound-command silent-death class.
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

    d = Path(hook_dir) if hook_dir is not None else _canonical_hooks_dir()
    prefix = f"uv run --project {d.parent.as_posix()} "
    for c in cmds:
        base = c.replace("\\", "/").rsplit("/", 1)[-1]
        if base not in expected:
            continue  # unrelated entries are not this registration's claim
        if not (c.startswith(prefix)
                and c[len(prefix):].startswith(d.as_posix() + "/")):
            mismatches.append(
                f"shape: command for {base} is not canonical (must be "
                f"uv-form into the declared hooks dir {d}): {c}")

    return {"ok": not mismatches, "layer": layer, "target": str(target),
            "mismatches": mismatches, "present": present, "missing": missing}


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
              f".claude/settings.json (issue #258); global deployment is "
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

    # hook_dir: the CANONICAL deployed skill hooks dir — NOT this module's
    # own location (#269; running from a worktree must not bind hook commands
    # to the worktree path, which dies with it — #228).
    hook_dir = _canonical_hooks_dir()

    def _ensure(entries: list, matcher: str, hook_file: str) -> tuple[list, bool]:
        new = [e for e in entries if e.get("matcher") == matcher]
        other = [e for e in entries if e.get("matcher") != matcher]
        # remove legacy entries with the same basename (backslash paths from
        # pre-posix wire-up) so re-wiring replaces them, not stacks.
        new = [
            e for e in new
            if not any((h.get("command", "").replace("\\", "/").rsplit("/", 1)[-1] == hook_file) for h in e.get("hooks", []))
        ]
        new.append(build_hook_entry(hook_dir, hook_file, matcher))
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
        kept.append(build_hook_entry(hook_dir, hook_file, None))
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
    post, added = _ensure(post, "Agent", "worker_budget.py")
    count += added
    post, added = _ensure(post, "Agent", "worker_pulse.py")
    count += added
    # state_anchor (#44): per-turn mechanical state re-anchor on every worker
    # completion — the L1 PREVENT layer (F5 forget/refresh).
    post, added = _ensure(post, "Agent", "state_anchor.py")
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
    check = selfcheck_registration(
        settings_path,
        expected_files=_wire_up_hook_files(),
        hook_dir=hook_dir,
        workspace=workspace,
        layer="user-opt-in" if global_opt_in else "project")
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
