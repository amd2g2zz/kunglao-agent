#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.9.37 — hooks_selfcheck.py (root-cause fix for recurring 'heartbeat/monitoring lost').

Incident (2026-08-05 14:20): ~/.claude/settings.json had its entire `hooks` segment
dropped by an unrelated settings rewrite (enabledPlugins/env/statusLine keys were
preserved, hooks vanished). All kunglao hooks (heartbeat_touch + worker_budget +
dispatch_gate + worker_pulse) disappeared -> mechanical heartbeat stopped (last_tick
frozen, back to cron-cognitive refresh) -> user report 'heartbeat lost again'. This
is the SAME class as the v1.9.18 'settings rewrites drop hooks' failure: any settings
mutation by Claude Code UI / plugin toggle / enabledPlugins change can silently omit
the hooks key, and nothing restores it.

This script is the mechanical cure. Run every heartbeat tick (step 0 of the tick,
it (a) import-time verifies all 9 WIRE_UP_HOOK_FILES registry entries via
derive_hook_subset and (b) run-time checks the 4 liveness-chain hooks
PROJECT-level <workspace>/.claude/settings.json — the wire-up deployment target since
issue #258 (2026-08-12; pre-#258 wrote the user-global file and bound hooks to a
worktree path that died with the worktree). If project-level is missing any hook, it
auto-rebuilds via hook_activation.py --wire-up (which now writes the project-level
file). The user-global ~/.claude/settings.json is NOT a deployment target anymore:
if it still carries kunglao hooks, this script prints a migration warning (remove
them from global; they must live in the project settings) but never rewrites it.

Wires in via heartbeat_loop_prompt.py (step 0 of every tick). Idempotent + fast (<50ms).
"""


# issue 275 batch-3: fail-open handlers keep their liveness posture (never
# raise, never change the return shape) but must leave ONE trace - a stderr
# WARN naming the operation + reason, rate-limited to once per op until the
# reason changes (the _zof_warn pattern of issue 276; one ws per process,
# so op is the key).
import sys
_WARN_LAST: dict[str, str] = {}


def warn(op: str, reason: str) -> None:
    if _WARN_LAST.get(op) == reason:
        return
    _WARN_LAST[op] = reason
    print(f"[kunglao-agent] hooks_selfcheck WARN (fail-open): "
          f"{op}: {reason}",
          file=sys.stderr)
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import wire_up_settings

# #536: template version stamp verify (init writes, selfcheck verifies —
# same shape as the state_hash contract).
import template_version  # noqa: E402

# #412: liveness thresholds are single-sourced in liveness_policy — the
# scheduler-freshness derivation and the component-source staleness budget
# both derive from the tick cadence.
from liveness_policy import (  # noqa: E402
    SCHEDULER_STALE_TICKS,
    TICK_INTERVAL_DEFAULT_MIN,
)

# #863 Family C: workspace resolution is single-sourced in ws_layout
# (the #228 strict family: arg wins, probe, exit 2 — never guess).
from ws_layout import resolve_strict as _resolve_ws  # noqa: E402

# #381: KONG_HOOK_FILES is a DELIBERATE narrow subset of the hook registry
# (wire_up_settings.WIRE_UP_HOOK_FILES) — the mechanical liveness chain this
# self-repair verifies (the 4 hooks from the v1.9.37 'heartbeat lost'
# incident). The other registry files (env_check_gate/recall_inject/
# state_anchor/completion_gate) are deployment gates whose drops env_check's
# full-registry scan catches. Derived from the registry via
# wire_up_settings.derive_hook_subset: a registry rename/growth raises
# loudly at import instead of this script silently checking a stale 4.
_KONG_CHAIN_FILES = (
    "heartbeat_touch.py",   # liveness refresh on any tool use
    "worker_budget.py",     # budget/tier enforcement
    "dispatch_gate.py",     # dispatch contract gate
    "worker_pulse.py",      # completion pulse
)
_KONG_SKIP_FILES = frozenset({
    "env_check_gate.py",    # env hard-gate — env_check scans it
    "recall_inject.py",     # recall injector — env_check scans it
    "state_anchor.py",      # state re-anchor — env_check scans it
    "completion_gate.py",   # Stop completion gate — env_check scans it
    "write_guard.py",       # carrier write gate — env_check scans it (#532)
    "orchestrator_tool_guard.py",  # Bash maker-checker WARN — env_check scans it (#608)
    "violation_capture.py", # Bash violation recorder — env_check scans it (#718)
    "bash_fact_guard.py",   # Bash facts-write lint recorder — env_check scans it (#809)
})

# #381: validate the subset tables against the registry (raises on drift) —
# then build the ordered list from the chain tuple, which keeps this
# script's historical check order.
wire_up_settings.derive_hook_subset(
    wire_up_settings.WIRE_UP_HOOK_FILES,
    include=_KONG_CHAIN_FILES, skip=_KONG_SKIP_FILES,
    owner="hooks_selfcheck KONG_HOOK_FILES")
KONG_HOOK_FILES = list(_KONG_CHAIN_FILES)
# User-global settings: NOT a deployment target since #258. Checked only to warn
# about leftover kunglao hooks that should be migrated to the project level.
# #143: /kunglao-agent:upgrade now PURGES those leftovers (backup + WARN rails);
# this check stays as the between-upgrades tripwire and is behaviorally unchanged.
USER_SETTINGS = Path.home() / ".claude" / "settings.json"


from harness_common import utc_now_z as utc_now  # #863 Family F: single source (was a local def)


def check_settings(settings_path: Path) -> dict:
    if not settings_path.exists():
        return {"exists": False, "hooks_segment": False, "present": [], "missing": list(KONG_HOOK_FILES)}
    try:
        s = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"exists": True, "hooks_segment": False, "parse_error": str(exc), "present": [], "missing": list(KONG_HOOK_FILES)}
    hooks = s.get("hooks")
    if not hooks:
        return {"exists": True, "hooks_segment": False, "present": [], "missing": list(KONG_HOOK_FILES)}
    # #810: canonical shape — non-event keys ("Agent"/"Bash" promoted into
    # the key slot) are the bug shape; their entries never fire and must not
    # count toward `present`.
    try:
        import wire_up_settings as _wus
        shape_issues = _wus.registration_shape_issues(s)
    except Exception:
        shape_issues = []
    cmds = []
    for ev, entries in hooks.items():
        if ev not in getattr(_wus, "HOOK_EVENTS", frozenset()):
            continue
        for e in entries:
            for h in e.get("hooks", []):
                cmds.append(h.get("command", ""))
    present, missing = [], []
    for hf in KONG_HOOK_FILES:
        (present if any(hf in c for c in cmds) else missing).append(hf)
    return {"exists": True, "hooks_segment": True, "present": present,
            "missing": missing, "shape_issues": shape_issues}


def rebuild_project_level(workspace: Path) -> dict:
    """Auto-rebuild the PROJECT-level settings via --wire-up (writes
    <workspace>/.claude/settings.json since #258)."""
    skill_dir = Path(__file__).resolve().parent.parent  # kunglao-agent/ (scripts/ -> root)
    script = skill_dir / "scripts" / "hook_activation.py"
    try:
        r = subprocess.run(
            [sys.executable, str(script), str(workspace), "--wire-up"],
            capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace",
        )
        return {"rebuilt": True, "rc": r.returncode, "stdout_tail": r.stdout.strip()[-200:]}
    except Exception as exc:
        return {"rebuilt": False, "error": str(exc)}


def check_statusline(settings_path: Path) -> dict:
    """#142 keep-alive face: the project-level `statusLine` settings key must
    reference the repo renderer (scripts/statusline_render.mjs). Not a hook —
    a different key in the same #258 project file, checked by the same
    keep-alive discipline (lives and dies with the workspace). Absent file /
    unparseable settings -> not ok (repair face rewrites the key)."""
    try:
        from hook_activation import STATUSLINE_RENDER_FILE, STATUSLINE_SETTINGS_KEY
    except Exception as exc:  # noqa: BLE001 — keep-alive never crashes the tick
        return {"present": False, "ok": True, "command": None,
                "detail": f"statusline constants unavailable (fail-open): {exc}"}
    try:
        s = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"present": False, "ok": False, "command": None,
                "detail": f"unreadable settings ({exc})"}
    entry = s.get(STATUSLINE_SETTINGS_KEY) if isinstance(s, dict) else None
    cmd = str(entry.get("command", "")) if isinstance(entry, dict) else None
    ok = (isinstance(entry, dict) and entry.get("type") == "command"
          and STATUSLINE_RENDER_FILE in (cmd or ""))
    return {"present": bool(entry), "ok": ok, "command": cmd}


def repair_statusline(ws: Path) -> dict:
    """#142 repair face: re-register the project-scoped statusLine key via
    hook_activation.register_statusline (THE registration entry). Returns
    the registration report; never raises."""
    try:
        from hook_activation import register_statusline
        return register_statusline(ws)
    except Exception as exc:  # noqa: BLE001 — keep-alive never crashes the tick
        return {"ok": False, "error": str(exc)}


def check_stamp_version(ws: Path) -> dict:
    """#536: three-carrier template version stamp consistency.

    Faults are reported (report row + status line) but do NOT move the
    exit code here — hooks_selfcheck owns hook liveness; the stamp HARD
    gate is env_check's `template_version` row. A stamp fault printed
    every tick makes the drift visible in the operator stream without
    downing heartbeat repair for a cosmetic-to-hooks defect."""
    try:
        faults = template_version.verify_stamps(ws)
    except RuntimeError as exc:  # unreadable skill version — surface, don't crash
        return {"faults": {}, "error": str(exc)}
    return {"faults": faults}


# =========================================================================
# #412: component ACTIVATION checks — scaffold truth is not activation truth
# =========================================================================
# Gap 1 (#412): the self-check covered scaffold (files exist, hooks
# registered) but never answered: are the hooks ARMED (vs the v1.9.7
# dormant-by-design state), is the SCHEDULER ticking, is MCP registered
# AND approved, is the oracle face live? A workspace could be "self-check
# green" while operationally dead (the owner's web-lane live run: 3 green
# lights, dead workspace). Every failed check carries a remediation:
# auto-repair where the ownership tier allows, else a structured blocker
# naming the exact command/file.

SELF_CHECK_STATE_REL = "runs" / Path(".hooks-selfcheck.json")


def _parse_iso(value: str | None) -> datetime | None:
    """ISO8601 -> AWARE datetime; None on anything unparseable (fail-open).
    Offset-less strings normalize to UTC — a naive result would raise
    TypeError on comparison with `now(timezone.utc)` and take the whole
    component table down with it."""
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def read_activation_state(ws: Path) -> dict | None:
    """`.hook_state.json` — the v1.9.7 activation state. None on missing/
    corrupt file (fail-open; dormant-by-design reads as not-armed)."""
    p = ws / ".hook_state.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def check_component_hooks(ws: Path) -> dict:
    """hooks wired AND armed, per hook file.

    armed   = all KONG chain hooks registered in a project target AND
              .hook_state.json exists, unexpired, active_hooks non-empty.
    dormant = wired but the activation is missing/expired/empty — the
              v1.9.7 dormant-by-design state. YELLOW (advisory), never a
              blocker: dormancy outside a dispatch loop is by design; the
              tick's own --renew step re-arms it (#412: dormant is yellow
              at best, never green).
    partial/unwired = the wiring face (existing rebuild auto-repair); a
              failed rebuild stays a blocker (red).
    """
    from harness_common import utc_now_z as utc_now  # family F single source

    proj_check = check_settings(ws / ".claude" / "settings.json")
    wired_ok = bool(proj_check.get("hooks_segment")) \
        and not proj_check.get("missing")
    state = read_activation_state(ws)
    armed = False
    if state is not None:
        expires = _parse_iso(state.get("expires_at"))
        active = state.get("active_hooks") or []
        armed = (expires is not None
                 and datetime.now(timezone.utc) < expires
                 and bool(active))
    if not wired_ok:
        missing_n = len(proj_check.get("missing") or [])
        row = {
            "ok": False,
            "state": "partial" if proj_check.get("hooks_segment") else "unwired",
            "detail": (f"{missing_n} KONG chain hook(s) missing from project "
                       f"settings") if proj_check.get("hooks_segment")
            else "no kunglao hooks wired in the project settings",
            "ts": utc_now(),
        }
        if proj_check.get("shape_issues"):
            row["detail"] += "; shape issues present"
        row["remediation"] = {
            "kind": "blocker",
            "command": "python <skill>/scripts/hook_activation.py <ws> --wire-up",
            "file": str(ws / ".claude" / "settings.json"),
            "detail": "auto-repair: the self-check re-runs hook_activation "
                      "--wire-up (rebuild_project_level); a failed rebuild "
                      "stays a blocker",
        }
        return row
    if armed:
        return {"ok": True, "state": "armed",
                "detail": f"{len(KONG_HOOK_FILES)} hooks wired and armed",
                "ts": utc_now()}
    row = {"ok": False, "state": "dormant",
           "detail": "hooks wired but activation missing/expired/empty "
                     "(v1.9.7 dormant-by-design)",
           "ts": utc_now()}
    row["remediation"] = {
        "kind": "advisory",
        "command": "python <skill>/scripts/hook_activation.py <ws> --renew "
                   "(orchestrator Phase 0 / heartbeat renew)",
        "file": str(ws / ".hook_state.json"),
        "detail": "dormant renders yellow, never green (#412); the tick's "
                  "--renew step re-arms",
    }
    return row


def check_component_scheduler(ws: Path,
                              now: datetime | None = None) -> dict:
    """scheduler last-tick freshness: runs/.heartbeat.json `last_tick_ts`.

    Threshold derivation (#412): SCHEDULER_STALE_TICKS x interval_min,
    interval_min = the heartbeat file's interval_min, else
    TICK_INTERVAL_DEFAULT_MIN. A quiet non-looping workspace legitimately
    has no fresh tick — advisory (yellow), never a blocker: the
    alive/dead verdict stays the heartbeat_mtime HARD probe's domain.
    """
    from harness_common import utc_now_z as utc_now  # family F single source

    now = now or datetime.now(timezone.utc)
    hb = ws / "runs" / ".heartbeat.json"
    state = None
    try:
        state = json.loads(hb.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = None
    if not isinstance(state, dict):
        return {"ok": False, "state": "never",
                "detail": "no heartbeat state — the scheduler has never "
                          "ticked here",
                "threshold_min": SCHEDULER_STALE_TICKS
                * TICK_INTERVAL_DEFAULT_MIN,
                "interval_min": TICK_INTERVAL_DEFAULT_MIN,
                "remediation": {
                    "kind": "advisory",
                    "command": "uv run --project <skill_root> "
                               "scripts/heartbeat_tick.py <ws>",
                    "file": str(hb),
                    "detail": "never green until a real tick lands",
                },
                "ts": utc_now()}
    interval = state.get("interval_min")
    try:
        interval = int(interval)
        if interval <= 0:
            raise ValueError
    except (TypeError, ValueError):
        interval = TICK_INTERVAL_DEFAULT_MIN
    threshold_min = SCHEDULER_STALE_TICKS * interval
    last_tick = _parse_iso(state.get("last_tick_ts"))
    age_min = None
    if last_tick is not None:
        age_min = max(0.0, (now - last_tick).total_seconds() / 60.0)
    if last_tick is None or age_min > threshold_min:
        return {"ok": False, "state": "stale" if last_tick is not None
                else "never",
                "detail": (f"scheduler last tick {age_min:.0f}min ago "
                           f"> {threshold_min}min budget "
                           f"({SCHEDULER_STALE_TICKS} ticks x {interval}min)"
                           if last_tick is not None else
                           "heartbeat state carries no last_tick_ts"),
                "last_tick_ts": state.get("last_tick_ts"),
                "age_min": round(age_min, 1) if age_min is not None else None,
                "threshold_min": threshold_min,
                "interval_min": interval,
                "remediation": {
                    "kind": "advisory",
                    "command": "uv run --project <skill_root> "
                               "scripts/heartbeat_tick.py <ws>",
                    "file": str(hb),
                    "detail": "never green until a real tick lands",
                },
                "ts": utc_now()}
    return {"ok": True, "state": "fresh",
            "detail": (f"scheduler tick fresh ({age_min:.0f}min <= "
                       f"{threshold_min}min)") if age_min is not None
            else "scheduler tick fresh",
            "last_tick_ts": state.get("last_tick_ts"),
            "age_min": round(age_min, 1) if age_min is not None else None,
            "threshold_min": threshold_min,
            "interval_min": interval,
            "ts": utc_now()}


def check_component_mcp(ws: Path, project_type: str | None = None) -> dict:
    """MCP registered-and-approved per the #408 face (workspace .mcp.json +
    plugin-carried ONLY — the deleted user-global surface is never read).

    ok               = every applicable HARD manifest item registered AND no
                       workspace-scope entry hangs pending approval.
    pending_approval = workspace .mcp.json carries entries but the workspace
                       approval flag is off — the #408 pending-forever trap
                       (auto-repairable: the approval merge is
                       ownership-tier-allowed).
    missing          = HARD manifest items unregistered -> BLOCKER.
    """
    from harness_common import utc_now_z as utc_now  # family F single source

    ptype = project_type or _read_project_type_local(ws) or "windows"
    import mcp_probe
    found = mcp_probe.registered_names(None, ws)
    hard_missing = []
    for item in mcp_probe.MANIFEST:
        if ptype not in item.types or item.tier != "HARD":
            continue
        if item.name not in found:
            hard_missing.append(item.name)
    ws_scoped = sorted(n for n, srcs in found.items()
                       if "workspace" in srcs)
    approval = mcp_probe.project_mcp_approval(ws)
    if ws_scoped and not approval:
        return {"ok": False, "state": "pending_approval",
                "registered": sorted(found),
                "ws_scoped": ws_scoped,
                "approval": False,
                "detail": ("workspace-scope server(s) "
                           f"{', '.join(ws_scoped[:4])} pending approval "
                           "forever (the approval record lives in the "
                           "user-global config)"),
                "remediation": {
                    # The table is collected AFTER apply_mcp_repairs — a
                    # surviving pending_approval means the auto-repair
                    # FAILED to clear it (e.g. read-only settings), so it
                    # must strict-gate, not silently pass.
                    "kind": "blocker",
                    "command": None,
                    "file": str(ws / ".claude" / "settings.json"),
                    "detail": (f"merge {mcp_probe.APPROVAL_KEY}: true into "
                               "the workspace settings (apply_mcp_repairs "
                               "attempts this every run; a surviving "
                               "pending-approval row means it failed)"),
                },
                "ts": utc_now()}
    if hard_missing:
        register_hint = next(
            (i.register for i in mcp_probe.MANIFEST
             if i.name == hard_missing[0]),
            "see scripts/mcp_probe.py MANIFEST")
        return {"ok": False, "state": "missing",
                "registered": sorted(found),
                "approval": approval,
                "detail": f"HARD item(s) not registered: "
                          f"{', '.join(hard_missing)}",
                "remediation": {
                    "kind": "blocker",
                    "command": register_hint,
                    "file": str(ws / ".mcp.json"),
                    "camoufox_note": "camoufox-reverse ships with the "
                                     "plugin (#408) — enable the plugin",
                },
                "ts": utc_now()}
    return {"ok": True, "state": "ok",
            "registered": sorted(found),
            "approval": approval,
            "detail": (f"{len(found)} server(s) registered in the #408 "
                       "surfaces; approval ok"),
            "ts": utc_now()}


def check_component_oracle(ws: Path) -> dict:
    """oracle face: task-oracle.yaml registered (heartbeat_tick's
    _oracle_registered single source, lazy import, fail-open).
    Unregistered = the completion-gate chain is unpowered -> BLOCKER
    (#473)."""
    from harness_common import utc_now_z as utc_now  # family F single source

    try:
        from heartbeat_tick import _oracle_registered
        ok = bool(_oracle_registered(ws))
    except Exception as exc:  # noqa: BLE001 — a face never crashes the check
        return {"ok": False, "state": "unregistered",
                "detail": f"oracle face unavailable: {exc}",
                "remediation": {
                    "kind": "blocker",
                    "command": None,
                    "file": str(ws / "task-oracle.yaml"),
                    "detail": "write the user's task verbatim into "
                              "task-oracle.yaml (Phase 0 backfill)",
                },
                "ts": utc_now()}
    if not ok:
        return {"ok": False, "state": "unregistered",
                "detail": "task-oracle.yaml missing/skeleton-only — the "
                          "closing gate chain is unpowered (#473)",
                "remediation": {
                    "kind": "blocker",
                    "command": None,
                    "file": str(ws / "task-oracle.yaml"),
                    "detail": "write the user's task verbatim into "
                              "task-oracle.yaml (Phase 0 backfill)",
                },
                "ts": utc_now()}
    return {"ok": True, "state": "registered",
            "detail": "task-oracle.yaml registered",
            "ts": utc_now()}


def check_component_ledger(ws: Path) -> dict:
    """ledger presence face: runs/logs/kunglao-*.jsonl. Absent = pre-loop
    (no events yet) — ADVISORY, never a blocker (a fresh workspace is
    legitimately quiet)."""
    from harness_common import utc_now_z as utc_now  # family F single source

    logs = ws / "runs" / "logs"
    try:
        present = any(logs.glob("kunglao-*.jsonl"))
    except OSError:
        present = False
    if present:
        return {"ok": True, "state": "present",
                "detail": "ledger present", "ts": utc_now()}
    return {"ok": False, "state": "absent",
            "detail": "no ledger yet — no analysis events emitted (pre-loop "
                      "workspaces are legitimately quiet)",
            "remediation": {
                "kind": "advisory",
                "command": None,
                "file": None,
                "detail": "expected before the first dispatch; not "
                          "repairable",
            },
            "ts": utc_now()}


def _read_project_type_local(ws: Path) -> str | None:
    """project_type from analysis_state.txt (best-effort local read)."""
    state = ws / "analysis_state.txt"
    if not state.exists():
        return None
    for line in state.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("project_type="):
            return line.split("=", 1)[1].strip()
    return None


def component_table(ws: Path, project_type: str | None = None,
                    now: datetime | None = None) -> tuple[dict, list[dict]]:
    """The #412 component activation table: {name: row} + flat blockers.

    A blocker is a RED state (partial/unwired hooks, missing/pending MCP,
    unregistered oracle) that strict mode gates on. Advisory rows (dormant
    hooks, stale/never scheduler, absent ledger) are yellow — surfaced with
    a named remediation, never green, never strict-gating (#412: dormant is
    yellow at best)."""
    comps = {
        "hooks": check_component_hooks(ws),
        "scheduler": check_component_scheduler(ws, now=now),
        "mcp": check_component_mcp(ws, project_type),
        "oracle": check_component_oracle(ws),
        "ledger": check_component_ledger(ws),
    }
    blockers: list[dict] = []
    for name, row in comps.items():
        remediation = row.get("remediation") or {}
        if row.get("ok") is False and remediation.get("kind") == "blocker":
            blockers.append({
                "component": name,
                "check": row.get("state"),
                "detail": row.get("detail"),
                "fix_command": remediation.get("command"),
                "fix_file": remediation.get("file"),
            })
    return comps, blockers


def apply_mcp_repairs(ws: Path) -> dict:
    """#412 auto-repairs the ownership tier allows (idempotent):
      1. scaffold <ws>/.mcp.json when ABSENT (never overwrites — the same
         never-shadow contract as init);
      2. merge enableAllProjectMcpServers: true into the workspace settings
         (#408 CRITICAL: the sudo-free approval writer)."""
    import mcp_probe
    out: dict = {}
    ws_mcp = ws / ".mcp.json"
    if not ws_mcp.exists():
        try:
            ws_mcp.write_text(json.dumps(mcp_probe.build_scaffold_json(),
                                         indent=2, ensure_ascii=False),
                              encoding="utf-8")
            out["scaffold"] = {"changed": True, "path": str(ws_mcp)}
        except OSError as exc:
            out["scaffold"] = {"changed": False, "error": str(exc)}
    if ws_mcp.exists():
        out["approval"] = mcp_probe.ensure_project_mcp_approval(ws)
    return out


def main_with_ws(ws: Path, strict: bool = False) -> int:
    """main() on an explicit workspace (the test seam). `strict=True` is
    the #412 closure face: exit 1 on any blocker (init/upgrade run the
    self-check with --strict at the end and gate on it)."""
    argv = [str(ws)] + (["--strict"] if strict else [])
    return main(argv)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:]) if argv is None else list(argv)
    strict = "--strict" in args
    positional = [a for a in args if not a.startswith("-")]
    ws = _resolve_ws(positional[0] if positional else None)
    proj_settings = ws / ".claude" / "settings.json"
    proj_check = check_settings(proj_settings)
    user_check = check_settings(USER_SETTINGS)

    # #258: user-global is NOT a deployment target. Leftover kunglao hooks there
    # are a migration hazard (worktree-bound paths) — warn, never rewrite.
    migration_warning = None
    if user_check.get("hooks_segment") and user_check.get("present"):
        migration_warning = (
            f"WARNING: kunglao hooks still present in user-global {USER_SETTINGS} "
            f"— migrate them to the project-level {proj_settings} and remove from "
            f"global (issue #258: global hooks bind to a worktree path and die "
            f"with it). This script never rewrites the global file."
        )
        print(migration_warning, file=sys.stderr)

    rebuilt = {}
    if proj_check.get("hooks_segment") is False or proj_check.get("missing"):
        rebuilt = rebuild_project_level(ws)
        if rebuilt.get("rc") == 0:
            # maker-checker: re-read the file — don't trust the subprocess claim.
            proj_check = check_settings(proj_settings)

    # #142: statusline keep-alive — same project file, different key. The
    # hooks rebuild above already re-registers the statusline (wire-up flow);
    # when hooks were fine but the statusLine key drifted, repair just it.
    # Cosmetic face: a failed repair is reported and WARNed, never fails
    # the tick (the rc weights stay hook-owned).
    sl_check = check_statusline(proj_settings)
    sl_repair: dict = {}
    if not sl_check.get("ok"):
        sl_repair = repair_statusline(ws)
        if sl_repair.get("ok"):
            sl_check = check_statusline(proj_settings)
        else:
            print(f"WARNING: statusline keep-alive repair failed "
                  f"({sl_repair.get('error') or sl_repair}) — the statusLine "
                  f"key stays missing from {proj_settings}", file=sys.stderr)

    # #412 auto-repairs (both modes, idempotent): the MCP ownership-tier
    # repairs — .mcp.json scaffold when absent (never overwrite) + the
    # #408 sudo-free approval merge. Recorded in the report; a failure is
    # WARNed and surfaces as the component row's blocker, never crashes.
    mcp_repairs: dict = {}
    try:
        mcp_repairs = apply_mcp_repairs(ws)
    except Exception as exc:  # noqa: BLE001 — repair never kills the check
        warn("mcp_repairs", f"{type(exc).__name__}: {exc}")
        mcp_repairs = {"error": str(exc)}

    # #412: the component activation table — collected AFTER the repairs so
    # the persisted truth is post-repair (same maker-checker re-read
    # discipline as the hook rebuild above).
    try:
        components, blockers = component_table(ws)
    except Exception as exc:  # noqa: BLE001 — a component crash must not
        # kill the tick's step 0; degrade to an unknown-components report.
        warn("component_table", f"{type(exc).__name__}: {exc}")
        components, blockers = {}, [{"component": "components",
                                     "check": "crashed",
                                     "detail": str(exc),
                                     "fix_command": None, "fix_file": None}]

    report = {
        "ts": utc_now(),
        "project_settings": str(proj_settings),
        "user_settings": str(USER_SETTINGS),
        "project_level": proj_check,
        "user_level": user_check,
        "user_migration_warning": migration_warning,
        "project_rebuild": rebuilt,
        "statusline": {**sl_check, "repair": sl_repair},
        # #412: component activation truth — the SINGLE source the
        # statusline component probes read (runs/.hooks-selfcheck.json).
        "components": components,
        "blockers": blockers,
        "mcp_repairs": mcp_repairs,
        # #536: stamp faults = per-carrier missing/mismatch map
        "template_version_stamps": check_stamp_version(ws),
    }
    out = ws / "runs" / ".hooks-selfcheck.json"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except Exception as exc:
        warn("main", f"{type(exc).__name__}: {exc}")

    proj_ok = proj_check.get("hooks_segment") and not proj_check.get("missing")
    status = f"project={'OK' if proj_ok else 'MISSING ' + str(proj_check.get('missing'))}"
    # #142: statusline keep-alive rides the status line (non-fatal).
    status += f" statusline={'OK' if sl_check.get('ok') else 'MISSING'}"
    if migration_warning:
        status += " (global has leftover kunglao hooks — migrate)"
    # #536: stamp faults ride the status line (non-fatal here — see
    # check_stamp_version docstring).
    stamp_faults = report["template_version_stamps"].get("faults") or {}
    if stamp_faults:
        status += (f" (template_version stamp faults: "
                   f"{', '.join(f'{k}={v}' for k, v in sorted(stamp_faults.items()))})")
    # #412: the component table rides the status line; strict mode gates on
    # the blockers (exit clean only when green, else the structured
    # remediation list — the init/upgrade closure face).
    status += " components=" + json.dumps(
        {k: v.get("state") for k, v in components.items()},
        ensure_ascii=False, sort_keys=True)
    print(f"hooks_selfcheck: {status}")
    for b in blockers:
        fix = b.get("fix_command") or b.get("fix_file") or ""
        print(f"  BLOCKER [{b['component']}/{b['check']}]: {b['detail']}"
              + (f" — fix: {fix}" if fix else ""))
    if strict and blockers:
        print(f"hooks_selfcheck --strict: {len(blockers)} blocker(s) — "
              "exit 1 (init/upgrade closure face, #412)")
        return 1
    return 0 if proj_ok else 1


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())
