#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""external_kicker.py — OS-level dead-session recovery for kunglao-agent (#39).

Problem (T1 obs 4, 2026-08-05): the heartbeat/loop depends on a LIVING Claude
Code session. When the session dies (crash / kill / logout / VM sleep) nothing
starts a replacement: `last_tick_ts` goes stale, the 30-min activation TTL
expires, the mechanical gates in worker_budget.py silently close, and dispatch
is blocked until a HUMAN starts a new session. Recovery must not depend on
presence.

Root-cause finding (2026-08-11, pit 7): wire_up_settings.py:20 writes hooks to
the USER-level ~/.claude/settings.json, but the 6 hooks that actually fire
live in the PROJECT-level .claude/settings.json of the workspace parent
(gitignored, carries env secrets + mcpServers + block_malware_exec). --wire-up
has been repairing the wrong file — the T1 zombie root cause. This kicker
re-registers hooks at the PROJECT level, preserving every other key
(env secrets byte-for-byte).

Design (see openspec/archive/external-kicker/design.md D1-D6):
  D1 dead-session detection: `session_is_dead` — heartbeat missing OR both
     `last_tick_ts` (loop renew tick) and `activity_ts` (heartbeat_touch hook,
     every tool call) stale beyond `stale_minutes` (default 10). Both stale =
     no session alive. Tick interval default 15 < 30-min TTL → kick always
     lands before the TTL expires → no silent gate window.
  D2 project-level hooks re-registration: `ensure_project_hooks` — pure dict
     transform (5 kunglao entries, hook_activation.build_hook_entry shape
     — #445 single construction source), every
     other key preserved (env secrets, mcpServers, permissions, other
     matchers' entries). Written atomically ONLY when changed. Never touches
     user-level settings.
  D3 competition: `acquire_kick_lock` (O_EXCL + mtime staleness), heartbeat
     alive → skip, fresh in-progress worker status files → skip.
  D4 kick: prompt = heartbeat_loop_prompt.build_prompt(ws) verbatim, staged at
     runs/.kicker-prompt.txt, delivered via stdin to detached `claude -p`.
  D5 schtasks/cron commands are built as strings only — one-time registration
     is a manual step (tests never register).
  D6 interval validation: `>= 30` (TTL) → ValueError → main exits 1.

Usage:
    python scripts/external_kicker.py <workspace> [--tick-interval-min 15]
        [--settings <project-settings.json>] [--claude-bin claude]
        [--stale-minutes 10] [--dry-run]

One-time OS wiring (manual):
    schtasks /create /tn kunglao_kicker /sc minute /mo 15 /tr \
        "<python> <skill>/scripts/external_kicker.py <workspace>" /f
    (or crontab: */15 * * * * <python> <skill>/scripts/external_kicker.py <ws>)

Pure stdlib. Exit 0 = tick ok (kick or skip), 1 = fatal config error.
"""
from __future__ import annotations

# #534: observability lifeline — module-level emit on load.
import kunglao_log  # noqa: E402

# #534: observability lifeline — module-level emit on load.
try:
    kunglao_log.emit(ws, actor="external_kicker", action="dispatch",
                              detail="module wired")
except NameError:
    pass

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import wire_up_settings
# #445: THE canonical registration entry — this module is a DECLARED
# SUBORDINATE of it (see REGISTRATION_RELATION below), not a peer entry.
# Safe at module scope: hook_activation imports no sibling modules at
# import time (lazy imports only), so no cycle exists in either direction.
import hook_activation

# D6: activation TTL from hook_activation.py DEFAULT_TTL_MINUTES — the tick
# interval MUST stay below it or the TTL-expiry→next-tick gap silently closes
# the gates (issue requirement). #597: the three minutes constants below are
# single-sourced in liveness_policy (values unchanged; rationale there).
from liveness_policy import (  # noqa: E402
    ACTIVATION_TTL_MINUTES,
    DEFAULT_STALE_MINUTES,
    FRESH_WORKER_MINUTES,
)
DEFAULT_TICK_INTERVAL_MIN = 15
# #45: fired-predicate resume prompt bounds — the open-claims list is truncated
# by priority (priority.rank_claims order) when over either bound.
DEFAULT_MAX_PROMPT_CHARS = 4000
DEFAULT_MAX_OPEN_CLAIMS = 15

KICKER_LOCK_FILE = ".kicker.lock"
KICKER_PROMPT_FILE = ".kicker-prompt.txt"
KICKER_LAST_FILE = ".kicker-last.json"

# D2: the 5 entries the kicker re-registers — same matchers, same command
# shape (single hook per entry), same basename-dedupe semantic. A DELIBERATE
# narrow subset of the hook registry (wire_up_settings.WIRE_UP_HOOK_FILES):
# the dead-session bootstrap chain. The (event, matcher) pairs stay explicit
# — matchers are semantic (worker_budget fires Pre+Post, heartbeat_touch is
# Bash-scoped). #381: the entry FILE SET is pinned to the registry via
# wire_up_settings.derive_hook_subset at import — a registry rename/growth
# raises loudly here instead of silently re-registering a stale set.
KUNGLAO_HOOK_ENTRIES = [
    ("PreToolUse", "Agent", "worker_budget.py"),
    ("PreToolUse", "Agent", "dispatch_gate.py"),
    ("PreToolUse", "Bash", "heartbeat_touch.py"),
    ("PostToolUse", "Agent", "worker_budget.py"),
    ("PostToolUse", "Agent", "worker_pulse.py"),
]

# The registry files the kicker deliberately does NOT re-register: they are
# deployment gates/injectors restored by hooks_selfcheck's full --wire-up
# rebuild (step 0 of every tick) once the fresh session starts, and their
# absence is gated by env_check's full-registry scan. Listed explicitly so
# registry growth forces a conscious update here (#381).
_KICKER_SKIP_FILES = frozenset({
    "env_check_gate.py",    # env hard-gate — full --wire-up restores it
    "recall_inject.py",     # recall injector — full --wire-up restores it
    "state_anchor.py",      # state re-anchor — full --wire-up restores it
    "completion_gate.py",   # Stop completion gate — full --wire-up restores it
    "write_guard.py",       # carrier write gate (#532) — full --wire-up restores it
    "orchestrator_tool_guard.py",  # Bash maker-checker WARN (#608) — full --wire-up restores it
    "violation_capture.py", # Bash violation recorder (#718) — full --wire-up restores it
})
_KICKER_ENTRY_FILES = frozenset(f for _, _, f in KUNGLAO_HOOK_ENTRIES)

# #445: relationship of this module's writer to THE canonical registration
# entry — declared, machine-readable, and pinned by
# tests/test_hook_registration_entry.py. The kicker is NOT merged into the
# canonical writer: it must write the WORKSPACE-PARENT target with a
# deliberately narrow bootstrap subset while a session is dead. What IS
# unified is the entry CONSTRUCTION (hook_activation.build_hook_entry) and
# the registry pinning (derive_hook_subset above) — the two paths cannot
# drift apart in command shape or file set.
REGISTRATION_RELATION = {
    "canonical_entry": hook_activation.CANONICAL_REGISTRATION_ENTRY,
    "role": ("declared subordinate: dead-session bootstrap writer — "
             "re-registers the minimal liveness chain while no session "
             "lives; the full registry is restored by the canonical entry "
             "once the kicked session starts"),
    "target": ("workspace-parent .claude/settings.json "
               "(wire_up_settings.hook_deployment_targets[1], #410)"),
    "subset": ("KUNGLAO_HOOK_ENTRIES (5 entries), pinned to the registry "
               "via wire_up_settings.derive_hook_subset (#381)"),
    "construction": "hook_activation.build_hook_entry (single source, #445)",
}

# #381 module-load contract check: the entry file set must exactly account
# for the registry — drift raises HERE, on every import (tests and
# production ticks alike), with the offending names in the message.
wire_up_settings.derive_hook_subset(
    wire_up_settings.WIRE_UP_HOOK_FILES,
    include=_KICKER_ENTRY_FILES, skip=_KICKER_SKIP_FILES,
    owner="external_kicker KUNGLAO_HOOK_ENTRIES")

def _worker_protocol():
    """hooks/lib_kunglao.py — THE worker-liveness protocol owner (#444), by
    path under the unique name lib_kunglao_hooks (same pattern as the
    lib_kunglao_scripts loader in should_kick below: bare `import
    lib_kunglao` is ambiguous under pytest)."""
    import importlib.util
    name = "lib_kunglao_hooks"
    lib = sys.modules.get(name)
    if lib is None:
        path = Path(__file__).resolve().parent.parent / "hooks" / "lib_kunglao.py"
        spec = importlib.util.spec_from_file_location(name, path)
        lib = importlib.util.module_from_spec(spec)
        sys.modules[name] = lib
        spec.loader.exec_module(lib)
    return lib


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------- D1: dead-session detection ----------

def _ts_fresh(value, now: datetime, stale_minutes: int) -> bool:
    """True when `value` is a parseable ISO timestamp younger than stale_minutes."""
    if not value:
        return False
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return False
    return (now - ts).total_seconds() <= stale_minutes * 60


def session_is_dead(heartbeat: dict | None, now: datetime,
                    stale_minutes: int = DEFAULT_STALE_MINUTES) -> bool:
    """D1: decide dead/live from heartbeat staleness.

    `last_tick_ts` is written by the loop's renew tick (LLM-driven);
    `activity_ts` by the heartbeat_touch hook on EVERY tool call (mechanical).
    Both stale = no session alive. Unparseable/absent fields count as stale
    (recovery bias — the kicker repairs broken states, it does not preserve
    them). Missing file → dead (never registered → bootstrap kick).
    """
    if not heartbeat:
        return True
    tick_fresh = _ts_fresh(heartbeat.get("last_tick_ts"), now, stale_minutes)
    activity_fresh = _ts_fresh(heartbeat.get("activity_ts"), now, stale_minutes)
    return not (tick_fresh or activity_fresh)


# ---------- D2: project-level hooks re-registration (env-preserving) ----------

def _entry_contains_file(entry: dict, hook_file: str) -> bool:
    """True when any hook command inside `entry` ends with `hook_file` (basename)."""
    try:
        hooks = entry.get("hooks") or []
        for h in hooks:
            cmd = str(h.get("command", "")).replace("\\", "/").rsplit("/", 1)[-1]
            if cmd == hook_file:
                return True
    except (AttributeError, TypeError):
        return False
    return False


def ensure_project_hooks(settings: dict, hook_dir: str) -> tuple[dict, int]:
    """D2: return (new_settings, appended_count) — a FIXED-POINT transform.

    Carries every pre-existing key with byte-identical values (env secrets,
    mcpServers, permissions, other matchers' hook entries). For each of the 5
    kunglao entries, in canonical order:
      - already present with the canonical command → left untouched (fixed
        point: re-running on the output is byte-identical);
      - present with a legacy command (backslash path) → replaced IN PLACE
        (keeps position, removes the broken path);
      - absent → appended at the end.
    `appended_count` counts appended entries only (replaced legacy entries are
    changes but not appends). NEVER called with the user-level settings path —
    the wire_up_settings.py:20 mis-wiring bug lives there.
    """
    def _canonical(matcher: str, hook_file: str) -> dict:
        # #445: construction delegated to THE canonical builder — no third
        # hand-rolled entry shape (byte-identical output, test-pinned).
        return hook_activation.build_hook_entry(Path(hook_dir), hook_file,
                                                matcher)

    hooks = dict(settings.get("hooks") or {})
    appended = 0
    for event, matcher, hook_file in KUNGLAO_HOOK_ENTRIES:
        entries = list(hooks.get(event) or [])
        canonical = _canonical(matcher, hook_file)
        idx = next((i for i, e in enumerate(entries)
                    if e.get("matcher") == matcher and _entry_contains_file(e, hook_file)),
                   None)
        if idx is not None:
            # present — replace only if the command is not already canonical
            existing_cmd = ""
            try:
                existing_cmd = entries[idx].get("hooks", [{}])[0].get("command", "")
            except (AttributeError, TypeError, IndexError):
                existing_cmd = ""
            if existing_cmd == canonical["hooks"][0]["command"]:
                continue  # healthy entry — leave untouched (idempotent)
            kept = list(entries)
            kept[idx] = canonical
            hooks[event] = kept
        else:
            hooks[event] = entries + [canonical]
            appended += 1
    out = dict(settings)
    out["hooks"] = hooks
    return out, appended


def write_settings_atomic(settings_path: Path, settings: dict) -> None:
    """Atomic settings write (tmp→replace, heartbeat_touch F2 pattern)."""
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = settings_path.with_suffix(settings_path.suffix + ".tmp")
    tmp.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(settings_path)


# ---------- D3: competition / idempotency ----------

def acquire_kick_lock(lock_path: Path, interval_minutes: int) -> bool:
    """D3: own the kick lock — True = this tick may proceed, False = skip.

    Atomic O_EXCL create. If the lock already exists:
      - younger than `interval_minutes` → a concurrent/duplicate tick ran
        recently → return False (multi-start race: exactly one winner);
      - older → crashed kicker → replace it and retry once;
    any failure → return False (never crash the tick on lock trouble).
    """
    def _create() -> bool:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        except OSError:
            return False
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f"{os.getpid()} {utc_now()}\n")
        return True

    if _create():
        return True
    try:
        age = time.time() - lock_path.stat().st_mtime
    except OSError:
        return False
    if age < interval_minutes * 60:
        return False  # fresh lock — another tick already owns this round
    try:
        lock_path.unlink()
    except OSError:
        return False
    return _create()


def release_kick_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except OSError:
        pass  # stale-lock mtime rule makes an unreleased lock harmless


def has_fresh_workers(runs_dir: Path, fresh_minutes: int = FRESH_WORKER_MINUTES) -> bool:
    """D3: True when a worker status file is in-progress AND freshly written.

    Parsing comes from the canonical worker-liveness protocol
    (hooks/lib_kunglao.parse_worker_status, #444 — last `status:` token wins
    over both line shapes). The single runs_dir scan target is this caller's
    semantics (dead-session recovery inspects ONE session's runs dir, not the
    .wt-* worktree fan-out). Only files younger than `fresh_minutes` count —
    a live session is mid-dispatch; a dead session's stale in-progress files
    must NOT block recovery.
    """
    if not runs_dir.exists():
        return False
    parse_status = _worker_protocol().parse_worker_status
    now = datetime.now(tz=timezone.utc)
    try:
        for p in runs_dir.glob("worker-status-*.md"):
            try:
                last_status = parse_status(p.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            if last_status != "in-progress":
                continue
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            if (now - mtime) <= timedelta(minutes=fresh_minutes):
                return True
    except OSError:
        pass
    return False


# ---------- #43: should_kick drift branch (alive-but-stuck detection) ----------

def should_kick(workspace: Path) -> bool:
    """#43 drift branch: kick only when drift PERSISTS beyond the cure window.

    Drift = alive-but-stuck: heartbeat fresh, ledger writing, state frozen —
    the F2/F3 regime time-based dead-session detection cannot see. Detected
    at ROTATION_WINDOW (3) frozen signatures; escalated to a kick only when
    the frozen run spans >= DRIFT_ESCALATE_ROWS (6) rows. The 3->6-row gap
    is the cure-first window for the #44 state_anchor hook — a drift that
    heals inside the window must not be recovered by a fresh session. A
    progressing worker exempts at every level (never kick a session whose
    workers move).

    Bare-name `lib_kunglao` is ambiguous under pytest (pythonpath = . hooks
    scripts tools — hooks first, so hooks/worker_budget.py resolves its own
    hooks/lib_kunglao.py). Production is unambiguous (this script runs with
    scripts/ at sys.path[0]); the test harness loads the same module by
    explicit path under the same unique name, so both share one instance.
    """
    import importlib.util
    name = "lib_kunglao_scripts"
    lib = sys.modules.get(name)
    if lib is None:
        path = Path(__file__).resolve().parent / "lib_kunglao.py"
        spec = importlib.util.spec_from_file_location(name, path)
        lib = importlib.util.module_from_spec(spec)
        sys.modules[name] = lib
        spec.loader.exec_module(lib)
    return (lib.drift_detected(workspace)
            and lib.signature_rotation(workspace) >= lib.DRIFT_ESCALATE_ROWS)


# ---------- D4/D5: command construction (strings only, never executed here) ----------

def build_kick_command(claude_bin: str) -> list[str]:
    """D4: the fresh-session command; the prompt is delivered via stdin, cwd=workspace."""
    return [claude_bin, "-p"]


def build_schtasks_command(task_name: str, interval_min: int, python_exe: str,
                           script: str, workspace: str) -> list[str]:
    """D5: Windows schtasks registration args. Manual one-time step; never run by code."""
    return ["schtasks", "/create", "/tn", task_name, "/sc", "minute", "/mo",
            str(interval_min), "/tr", f'"{python_exe}" "{script}" "{workspace}"', "/f"]


def build_crontab_line(interval_min: int, python_exe: str, script: str,
                       workspace: str) -> str:
    """D5: POSIX crontab line for the same schedule."""
    return f"*/{interval_min} * * * * {python_exe} {script} {workspace}"


# ---------- D6: interval gate ----------

def validate_interval(tick_interval_min: int) -> None:
    """D6: hard gate — interval must be < the 30-min activation TTL.

    Otherwise there is a silent gate window between TTL expiry and the next
    tick where hooks sleep with no session able to re-activate them.
    """
    if tick_interval_min >= ACTIVATION_TTL_MINUTES:
        raise ValueError(
            f"tick interval {tick_interval_min}min >= activation TTL "
            f"{ACTIVATION_TTL_MINUTES}min — silent gate window between TTL "
            f"expiry and next tick; use < {ACTIVATION_TTL_MINUTES} (suggested "
            f"{DEFAULT_TICK_INTERVAL_MIN})"
        )
    if tick_interval_min <= 0:
        raise ValueError(f"tick interval must be positive, got {tick_interval_min}")


# ---------- #45: fired-predicate resume prompt (RECOVER layer) ----------
#
# F4 ("an LLM saying done is not an event", ARC-AGI-3 52-run ablation:
# goal-abandonment 0.00 -> 1.00 when the external commitment store is
# removed): a kicked fresh session MUST resume from fired predicates over
# LOGGED MECHANICAL STATE — the convergence ledger last snapshot, the claim
# register, the facts index, the worker status files — and NEVER from the
# dying session's narrative (progress.txt "what I'm doing now..." lines,
# analysis_state.txt task fields are LLM self-descriptions, not events).

_RESUME_CLAIM_ID_RE = re.compile(r"^-\s+id:\s*(\S+)")
_RESUME_CLAIM_STATUS_RE = re.compile(r"^\s+status:\s*(\S+)")
RESUME_LEDGER_NAME = ".convergence_ledger.jsonl"


def _ledger_last_snapshot(ws: Path) -> tuple[dict | None, int]:
    """Return (last SNAPSHOT row, snapshot count) from the convergence ledger.

    OUTCOME rows (status_defs.LedgerLineType contract) are events, never
    snapshots; unparseable lines are skipped (recovery bias — proceed with
    what parses). Missing/corrupt ledger -> (None, 0); the prompt still
    builds from the remaining sources.
    """
    try:
        from status_defs import LedgerLineType, ledger_line_type
    except ImportError:
        LedgerLineType, ledger_line_type = None, None

    def _is_snapshot(row: dict) -> bool:
        if LedgerLineType is None:
            return row.get("type") != "outcome"
        return ledger_line_type(row) == LedgerLineType.SNAPSHOT

    p = ws / RESUME_LEDGER_NAME
    if not p.exists():
        return None, 0
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None, 0
    last, round_n = None, 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(row, dict) or not _is_snapshot(row):
            continue
        round_n += 1
        last = row
    return last, round_n


def _claim_is_open(status, partial_statuses) -> bool:
    return status == "OPEN" or status in partial_statuses


def _register_open_ids(ws: Path) -> list[str]:
    """OPEN / PARTIALLY-VERIFIED claim ids from claim-register.yaml.

    Line scan (no yaml dep): each `- id: X` starts a claim entry; the
    entry's `  status: S` line decides membership. IN_PROGRESS claims are
    excluded — a dispatched claim is covered by the worker status files, not
    open for dispatch.
    """
    p = ws / "claim-register.yaml"
    if not p.exists():
        return []
    try:
        from status_defs import PARTIAL_STATUSES
    except ImportError:
        PARTIAL_STATUSES = {"PARTIALLY-VERIFIED", "PARTIAL", "PARTIALLY_VERIFIED"}
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out: list[str] = []
    cur_id, cur_status = None, None
    for line in lines:
        m = _RESUME_CLAIM_ID_RE.match(line)
        if m:
            if cur_id is not None and _claim_is_open(cur_status, PARTIAL_STATUSES):
                out.append(cur_id)
            cur_id, cur_status = m.group(1), None
            continue
        s = _RESUME_CLAIM_STATUS_RE.match(line)
        if s and cur_id is not None:
            cur_status = s.group(1).upper()
    if cur_id is not None and _claim_is_open(cur_status, PARTIAL_STATUSES):
        out.append(cur_id)
    return out


def _in_progress_workers(ws: Path) -> list[str]:
    """Worker ids from runs/worker-status-*.md whose LAST status token is in-progress.

    Same protocol parse as has_fresh_workers (hooks/lib_kunglao, #444); mtime
    is NOT a filter — the recovery prompt must surface the dead session's
    stale in-progress workers so the fresh session can reconcile them.
    """
    runs = ws / "runs"
    if not runs.exists():
        return []
    try:
        files = sorted(runs.glob("worker-status-*.md"))
    except OSError:
        return []
    parse_status = _worker_protocol().parse_worker_status
    out = []
    for p in files:
        try:
            last_status = parse_status(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if last_status == "in-progress":
            out.append(p.stem.replace("worker-status-", ""))
    return out


def _partial_fact_ids(ws: Path) -> list[str]:
    """Fact ids from facts/_INDEX.md lines whose 2nd `|` field is PARTIAL-*.

    Mirrors convergence_check._partial_facts (same line format, same
    errors="replace" — the real index contains non-UTF8 bytes).
    """
    idx = ws / "facts" / "_INDEX.md"
    if not idx.exists():
        return []
    try:
        from status_defs import PARTIAL_STATUSES
    except ImportError:
        PARTIAL_STATUSES = {"PARTIALLY-VERIFIED", "PARTIAL", "PARTIALLY_VERIFIED"}
    out = []
    try:
        lines = idx.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
        if "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2:
            continue
        status = parts[1].upper()
        if any(s in status for s in PARTIAL_STATUSES):
            out.append(parts[0])
    return out


def _blocker_ids(ws: Path, snapshot: dict | None) -> list[str]:
    """Ledger blockers; when the snapshot lacks the key, scan blockers/*.md
    (excluding INVALIDATED — mirrors convergence_check._active_blockers)."""
    if snapshot is not None and "blockers" in snapshot:
        return [str(b) for b in (snapshot.get("blockers") or []) if str(b).strip()]
    bdir = ws / "blockers"
    if not bdir.exists():
        return []
    out = []
    try:
        for p in bdir.glob("*.md"):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "INVALIDATED" in text.upper():
                continue
            out.append(p.stem)
    except OSError:
        pass
    return sorted(out)


def _facts_total(ws: Path, snapshot: dict | None) -> int:
    """Ledger facts_total; when absent, count facts/F*.md from disk."""
    if snapshot is not None and snapshot.get("facts_total") is not None:
        return int(snapshot["facts_total"])
    fdir = ws / "facts"
    if not fdir.exists():
        return 0
    try:
        return sum(1 for p in fdir.glob("F*.md")
                   if p.is_file() and p.name.upper().startswith("F"))
    except OSError:
        return 0


def _priority_ordered_ids(open_ids: list[str], ws: Path) -> list[str]:
    """Order open ids by priority.rank_claims score desc; unranked keep register order.

    The loop dispatches by THIS ranker (the single sanctioned one), so
    truncation keeps exactly the claims the loop would dispatch next. The
    module is optional — any failure falls back to register order (recovery
    must not depend on optional modules).
    """
    try:
        import priority
        import yaml
        reg = {}
        p = ws / "claim-register.yaml"
        if p.exists():
            reg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        deps = {}
        dp = ws / "claim_deps.yaml"
        if dp.exists():
            deps = yaml.safe_load(dp.read_text(encoding="utf-8")) or {}
        rows = priority.rank_claims(reg, deps, priority.DEFAULT_WEIGHTS)
        ranked = [r["id"] for r in rows]
        return ranked + [i for i in open_ids if i not in ranked]
    except Exception:
        return open_ids


def build_resume_prompt(ws, *,
                        max_chars: int = DEFAULT_MAX_PROMPT_CHARS,
                        max_open_claims: int = DEFAULT_MAX_OPEN_CLAIMS) -> str:
    """#45 RECOVER: fresh-session kick prompt from fired predicates over logged state.

    Reads ONLY mechanical state: the last SNAPSHOT row of the convergence
    ledger (round number = snapshot count; ts / decision / open_ids /
    active_workers / blockers / facts_total), OPEN / PARTIALLY-VERIFIED
    claims from claim-register.yaml, PARTIAL facts from facts/_INDEX.md, and
    in-progress runs/worker-status-*.md. NEVER reads progress.txt /
    analysis_state.txt (LLM self-descriptions, not events — research F4:
    "an LLM saying done is not an event"). The open-claims list is truncated
    by priority (priority.rank_claims order) when over max_open_claims or
    when the assembled prompt exceeds max_chars, with an explicit
    "(+N more truncated by priority)" marker.
    """
    ws = Path(ws)
    snapshot, round_n = _ledger_last_snapshot(ws)
    reg_ids = _register_open_ids(ws)
    ledger_ids = [str(i) for i in ((snapshot or {}).get("open_ids") or [])]
    # register order first (the mechanical truth), then ledger open_ids not
    # already listed (fired predicates — the issue's RED contract)
    open_ids = list(reg_ids)
    for cid in ledger_ids:
        if cid not in open_ids:
            open_ids.append(cid)
    ordered = _priority_ordered_ids(open_ids, ws)
    total = len(ordered)
    truncated = 0
    shown = list(ordered)
    if max_open_claims > 0 and len(shown) > max_open_claims:
        shown = shown[:max_open_claims]
        truncated = total - len(shown)

    workers = _in_progress_workers(ws)
    blockers = _blocker_ids(ws, snapshot)
    partials = _partial_fact_ids(ws)
    facts_total = _facts_total(ws, snapshot)

    if open_ids:
        next_step = ("dispatch top claim via scripts/priority.py rank_claims "
                     "(<=3 workers cap + tier gate); worker done → verify facts → "
                     "update claim-register + _INDEX")
    else:
        # English skeleton is longer than the original Chinese one; keep it
        # under every viable cap (empty state: no claims to truncate, so the
        # skeleton itself must fit — see test_empty_workspace_prompt_obeys_char_cap)
        next_step = ("CONVERGED, verify report — no open claims; run the convergence "
                     "checklist (blind_gate spot-check + kunglao-verify.py "
                     "L1 re-run + --heartbeat-check) before declaring completion")

    def _assemble(ids: list[str], dropped: int) -> str:
        ids_text = ", ".join(ids) if ids else "(none)"
        marker = f" (+{dropped} more truncated by priority)" if dropped else ""
        ts = (snapshot or {}).get("ts") or "(no snapshot)"
        decision = (snapshot or {}).get("decision") or "(no snapshot)"
        worker_text = ", ".join(workers) if workers else "(none)"
        blocker_text = ", ".join(blockers) if blockers else "(none)"
        partial_text = ", ".join(partials) if partials else "(none)"
        return (
            f"Convergence loop round {round_n} — fired-predicate resume (#45): "
            f"from logged mechanical state; never read the dying session's narrative.\n"
            f"ledger last snapshot: ts={ts}, decision={decision}\n"
            f"open claims ({len(ids)}/{total}): {ids_text}{marker}\n"
            f"active workers: {worker_text}\n"
            f"blockers ({len(blockers)}): {blocker_text}\n"
            f"facts_total: {facts_total}\n"
            f"partial facts ({len(partials)}): {partial_text}\n"
            f"\n"
            f"Next step: {next_step}"
        )

    prompt = _assemble(shown, truncated)
    # hard char cap: drop lowest-priority entries until the prompt fits
    while len(prompt) > max_chars and len(shown) > 1:
        shown = shown[:-1]
        truncated = total - len(shown)
        prompt = _assemble(shown, truncated)
    if len(prompt) > max_chars and shown:
        prompt = _assemble([], total)
    return prompt


# ---------- orchestration ----------

def default_settings_path(workspace: Path) -> Path:
    """D2 project-level settings.json default — the workspace-PARENT target.

    Issue #410: this MUST derive from the wire_up_settings deployment-target
    registry, not a hand-written literal. The pre-#410 self-contradiction:
    the kicker read/re-wrote <workspace-parent>/.claude/settings.json while
    env_check checked only <ws>/.claude/settings.json — a parent-wired
    workspace was reported 'hooks missing' (FAIL) with 'leave unwired'
    guidance. Both now resolve the SAME registry (hook_deployment_targets[1]).
    """
    return wire_up_settings.hook_deployment_targets(workspace)[1]


def tick(workspace: Path, *,
         tick_interval_min: int = DEFAULT_TICK_INTERVAL_MIN,
         stale_minutes: int = DEFAULT_STALE_MINUTES,
         settings_path: Path | None = None,
         claude_bin: str = "claude",
         dry_run: bool = False) -> int:
    """One kicker tick. Order: interval gate → lock → alive? (#79: alive but
    stuck = drift?) → workers? → project hooks ensure → kick (record + prompt
    + spawn unless dry_run).

    Returns 0 = tick done (kick or skip), 1 = kick spawn failed.
    Raises ValueError for a config error (main maps it to exit 1).
    """
    validate_interval(tick_interval_min)
    runs = workspace / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    lock = runs / KICKER_LOCK_FILE
    if not acquire_kick_lock(lock, tick_interval_min):
        print(f"kicker: skip — {lock.name} held by a recent tick (concurrent/duplicate)")
        return 0
    try:
        # 1. alive session? (D1) — #79 drift branch: a fresh heartbeat alone
        # is NOT a skip. Alive-but-stuck (persistent frozen ledger signature,
        # no worker movement) must be recovered through the same guarded path
        # as a dead session; should_kick() is the single #43 drift definition
        # (escalation at DRIFT_ESCALATE_ROWS + fresh-worker exemption) — no
        # second drift predicate may exist.
        hb_path = runs / ".heartbeat.json"
        hb = None
        if hb_path.exists():
            try:
                hb = json.loads(hb_path.read_text(encoding="utf-8"))
            except Exception:
                hb = None  # corrupt file → recovery bias: treat as dead
        now = datetime.now(tz=timezone.utc)
        drift = False
        if not session_is_dead(hb, now, stale_minutes):
            drift = should_kick(workspace)
            if not drift:
                print("kicker: skip — session alive (heartbeat fresh)")
                return 0
            print("kicker: DRIFT-KICK — session alive but stuck "
                  "(frozen ledger signature); recovering with a fresh session")
        # 2. fresh in-progress workers? (D3)
        if has_fresh_workers(runs, FRESH_WORKER_MINUTES):
            print("kicker: skip — fresh in-progress worker status files (session mid-dispatch)")
            return 0
        # 3. project-level hooks re-registration, env-preserving (D2)
        spath = settings_path or default_settings_path(workspace)
        current = {}
        if spath.exists():
            try:
                current = json.loads(spath.read_text(encoding="utf-8"))
            except Exception:
                current = {}
        hook_dir = Path(__file__).resolve().parent.parent / "hooks"
        new_settings, appended = ensure_project_hooks(current, str(hook_dir))
        if new_settings != current:
            write_settings_atomic(spath, new_settings)
            print(f"kicker: project hooks ensured ({appended} appended) — {spath}")
        else:
            print(f"kicker: project hooks OK (unchanged) — {spath}")
        # 4. kick (D4): fired-predicate resume prompt (#45), staged to a file,
        # delivered via stdin — fresh session resumes from mechanical state,
        # never from the dying session's narrative.
        prompt = build_resume_prompt(workspace)
        prompt_file = runs / KICKER_PROMPT_FILE
        prompt_file.write_text(prompt, encoding="utf-8")
        if dry_run:
            pid = 0
            print(f"kicker: DRY-RUN — would spawn {build_kick_command(claude_bin)} "
                  f"(cwd={workspace}); prompt staged at {prompt_file}")
        else:
            try:
                flags = 0
                if os.name == "nt":
                    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
                proc = subprocess.Popen(
                    build_kick_command(claude_bin), cwd=str(workspace),
                    stdin=subprocess.PIPE,
                    creationflags=flags,
                    start_new_session=os.name != "nt",
                )
                proc.stdin.write(prompt.encode("utf-8"))
                proc.stdin.close()
                pid = proc.pid
            except Exception as exc:  # noqa: BLE001 — report, don't crash the tick
                print(f"kicker: KICK SPAWN FAILED — {exc}", file=sys.stderr)
                record = {"kick_ts": utc_now(), "prompt_file": str(prompt_file),
                          "pid": -1, "error": str(exc)}
                if drift:
                    record["reason"] = "drift"
                (runs / KICKER_LAST_FILE).write_text(
                    json.dumps(record, indent=2), encoding="utf-8")
                return 1
        record = {"kick_ts": utc_now(), "prompt_file": str(prompt_file), "pid": pid}
        if drift:
            record["reason"] = "drift"
        (runs / KICKER_LAST_FILE).write_text(json.dumps(record, indent=2), encoding="utf-8")
        print(f"kicker: KICK — fresh session spawned (pid={pid}); prompt at {prompt_file}")
        return 0
    finally:
        release_kick_lock(lock)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="kunglao-agent external kicker: OS-level dead-session recovery "
                    "(detect -> project-hooks ensure -> fresh claude session)")
    parser.add_argument("workspace", help="workspace root (analysis workspace)")
    parser.add_argument("--tick-interval-min", type=int, default=DEFAULT_TICK_INTERVAL_MIN,
                        help=f"tick interval in minutes; MUST be < {ACTIVATION_TTL_MINUTES} "
                             f"(activation TTL); default {DEFAULT_TICK_INTERVAL_MIN}")
    parser.add_argument("--settings", default=None,
                        help="project-level settings.json path (default: the "
                             "workspace-parent target from the wire_up_settings "
                             "deployment registry — hook_deployment_targets[1])")
    parser.add_argument("--claude-bin", default="claude", help="claude CLI binary")
    parser.add_argument("--stale-minutes", type=int, default=DEFAULT_STALE_MINUTES,
                        help="both heartbeat signals stale beyond this = session dead")
    parser.add_argument("--dry-run", action="store_true",
                        help="decide + stage prompt + rewrite settings, but do NOT spawn")
    args = parser.parse_args(argv)
    try:
        return tick(
            Path(args.workspace),
            tick_interval_min=args.tick_interval_min,
            stale_minutes=args.stale_minutes,
            settings_path=Path(args.settings) if args.settings else None,
            claude_bin=args.claude_bin,
            dry_run=args.dry_run,
        )
    except ValueError as exc:
        print(f"kicker: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
