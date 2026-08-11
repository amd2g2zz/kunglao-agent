#!/usr/bin/env python3
"""external_kicker.py — OS-level dead-session recovery for kunglao-agent (#39).

Problem (T1 obs 4, 2026-08-05): the heartbeat/loop depends on a LIVING Claude
Code session. When the session dies (crash / kill / logout / VM sleep) nothing
starts a replacement: `last_tick_ts` goes stale, the 30-min activation TTL
expires, the mechanical gates in worker_budget.py silently close, and dispatch
is blocked until a HUMAN starts a new session. Recovery must not depend on
presence.

Root-cause finding (2026-08-11, 坑 7): wire_up_settings.py:20 writes hooks to
the USER-level ~/.claude/settings.json, but the 6 hooks that actually fire
live in the PROJECT-level .claude/settings.json of the workspace parent
(gitignored, carries env secrets + mcpServers + block_malware_exec). --wire-up
has been repairing the wrong file — the T1 zombie root cause. This kicker
re-registers hooks at the PROJECT level, preserving every other key
(env secrets byte-for-byte).

Design (see openspec/changes/external-kicker/design.md D1-D6):
  D1 dead-session detection: `session_is_dead` — heartbeat missing OR both
     `last_tick_ts` (loop renew tick) and `activity_ts` (heartbeat_touch hook,
     every tool call) stale beyond `stale_minutes` (default 10). Both stale =
     no session alive. Tick interval default 15 < 30-min TTL → kick always
     lands before the TTL expires → no silent gate window.
  D2 project-level hooks re-registration: `ensure_project_hooks` — pure dict
     transform (5 kunglao entries, wire_up_settings._ensure shape), every
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

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# D6: activation TTL from hook_activation.py DEFAULT_TTL_MINUTES — the tick
# interval MUST stay below it or the TTL-expiry→next-tick gap silently closes
# the gates (issue requirement).
ACTIVATION_TTL_MINUTES = 30
DEFAULT_TICK_INTERVAL_MIN = 15
# D1: both heartbeat signals stale beyond this → dead. 15+10 = worst-case
# detection ≤ 25 min < 30-min TTL → the kick always lands before the old
# activation expires (no silent window, with margin).
DEFAULT_STALE_MINUTES = 10
# D3: worker status files fresher than this block the kick (session mid-dispatch).
# Mirrors lib_kunglao STUCK_MINUTES (20).
FRESH_WORKER_MINUTES = 20

KICKER_LOCK_FILE = ".kicker.lock"
KICKER_PROMPT_FILE = ".kicker-prompt.txt"
KICKER_LAST_FILE = ".kicker-last.json"

# D2: the 5 entries wire_up_settings registers — same matchers, same command
# shape (single hook per entry), same basename-dedupe semantic.
KUNGLAO_HOOK_ENTRIES = [
    ("PreToolUse", "Agent", "worker_budget.py"),
    ("PreToolUse", "Agent", "dispatch_gate.py"),
    ("PreToolUse", "Bash", "heartbeat_touch.py"),
    ("PostToolUse", "Agent", "worker_budget.py"),
    ("PostToolUse", "Agent", "worker_pulse.py"),
]

_STATUS_RE = re.compile(r"status:\s*(\S+)")


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
        p = (Path(hook_dir) / hook_file).as_posix()  # POSIX: hooks run via sh -c
        return {"matcher": matcher,
                "hooks": [{"type": "command", "command": f"python {p}"}]}

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

    Mirrors lib_kunglao.scan_active_workers parsing (last `status:` line
    decides; lowercased). Only files younger than `fresh_minutes` count — a
    live session is mid-dispatch; a dead session's stale in-progress files
    must NOT block recovery.
    """
    if not runs_dir.exists():
        return False
    now = datetime.now(tz=timezone.utc)
    try:
        for p in runs_dir.glob("worker-status-*.md"):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            last_status = None
            for line in text.splitlines():
                m = _STATUS_RE.search(line)
                if m:
                    last_status = m.group(1).lower()
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


# ---------- orchestration ----------

def tick(workspace: Path, *,
         tick_interval_min: int = DEFAULT_TICK_INTERVAL_MIN,
         stale_minutes: int = DEFAULT_STALE_MINUTES,
         settings_path: Path | None = None,
         claude_bin: str = "claude",
         dry_run: bool = False) -> int:
    """One kicker tick. Order: interval gate → lock → alive? → workers? →
    project hooks ensure → kick (record + prompt + spawn unless dry_run).

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
        # 1. alive session? (D1)
        hb_path = runs / ".heartbeat.json"
        hb = None
        if hb_path.exists():
            try:
                hb = json.loads(hb_path.read_text(encoding="utf-8"))
            except Exception:
                hb = None  # corrupt file → recovery bias: treat as dead
        now = datetime.now(tz=timezone.utc)
        if not session_is_dead(hb, now, stale_minutes):
            print("kicker: skip — session alive (heartbeat fresh)")
            return 0
        # 2. fresh in-progress workers? (D3)
        if has_fresh_workers(runs, FRESH_WORKER_MINUTES):
            print("kicker: skip — fresh in-progress worker status files (session mid-dispatch)")
            return 0
        # 3. project-level hooks re-registration, env-preserving (D2)
        spath = settings_path or workspace.parent / ".claude" / "settings.json"
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
        # 4. kick (D4): loop prompt verbatim, staged to a file, delivered via stdin
        from heartbeat_loop_prompt import build_prompt
        prompt = build_prompt(str(workspace))
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
                (runs / KICKER_LAST_FILE).write_text(
                    json.dumps(record, indent=2), encoding="utf-8")
                return 1
        record = {"kick_ts": utc_now(), "prompt_file": str(prompt_file), "pid": pid}
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
                        help="project-level settings.json path (default: "
                             "<workspace-parent>/.claude/settings.json)")
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
