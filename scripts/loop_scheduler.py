#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""loop_scheduler.py — durable /loop registration writer (#754 E1, absorbs #616).

Why: init used to print the /loop prompt and WAIT for a human (or a lucky
orchestrator) to run CronCreate. Two field facts make that wait fatal:
  - Claude Code CronCreate defaults to SESSION-ONLY schedules — the cron dies
    with the process that created it (issue #616); nothing survives a reboot,
    a crash, or a context compaction.
  - "等人说就很蠢，不知道心跳机制的用户根本到不了提示" (user adjudication
    2026-08-27): users who don't understand the heartbeat machinery never
    reach the printed hint at all.

This module owns THE workspace-side registration artifact Claude Code itself
uses for durable schedules: ``<workspace>/.claude/scheduled_tasks.json``
(written by CronCreate(durable:true), resumed on session start). We upsert a
single identified entry (id=kunglao-heartbeat) and PRESERVE every foreign
entry byte-for-byte — workspaces may carry other scheduled jobs.

#593 red line — precise semantics: writing this SCHEDULER REGISTRY is NOT
faking ``loop_registered``. The marker's definition (#461) is "the /loop
prompt BODY really executed", and its only carrier is runs/.heartbeat.json.
This module never reads or writes the heartbeat file and never fakes tick
evidence; loop_registered still flips true only on the prompt's first real
action (--heartbeat-on --loop-registered). #618's crontab/register_daemon
route is explicitly REJECTED — Claude Code durable cron is the right path.

Reader tolerates four shapes of an existing file:
  [entry, ...]                 bare array
  {"jobs": [entry, ...]}       wrapper object (kunglao's own key)
  {"tasks": [entry, ...]}      wrapper object (harness key, #679)
  corrupt bytes                backed up to *.corrupt-<ts> then rebuilt

#679 schema war — the harness writes ``{"tasks": [...]}``; an earlier reader
only knew ``jobs``/bare arrays, so it quarantined harness files to
*.unrecognized-*, treated them as EMPTY, and rebuilt the file as
{"jobs": [...]} — destroying the harness's tasks key on every upsert while
exiling kunglao's own entries to sidecars. Both wrapper keys are now first-
class: reads pick the container (jobs preferred when both ride one document),
writes preserve the original container key AND every unknown sibling key
byte-for-byte in place. Fail-open: shapes we still don't understand keep the
r3-M1 sidecar backup — never a silent clobber.

Usage:
    python scripts/loop_scheduler.py <workspace>            # upsert, prints status
    python scripts/loop_scheduler.py <workspace> --check     # rc0 exists / rc2 missing

Pure stdlib. Exit 0 = written/verified OK, 1 = unexpected error, 2 = --check found no entry.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

JOB_ID = "kunglao-heartbeat"
JOB_NAME = "kunglao-agent heartbeat"
PROMPT_MARKERS = ("kunglao-agent heartbeat", "--heartbeat-on")

SCHEDULE_FILE_REL = Path(".claude") / "scheduled_tasks.json"

# Known entry-container keys, preferred order. "jobs" is kunglao's own key;
# "tasks" is the harness's key (#679 schema war) — both first-class, never
# clobbered. When a document carries BOTH, jobs wins as our container and
# tasks rides along as foreign data.
ENTRY_KEYS = ("jobs", "tasks")


from harness_common import utc_now_z as utc_now  # #863 Family F: single source (was a local def)
from kunglao_log import warn

import scheduler_events  # the drain face's stream source (scripts sibling)


# ==================== the scheduler events drain face ====================

# The event-driven wake path's session-side half — the CONSUMER of the
# watcher's staged wake artifact (runs/.scheduler-wake.json; the
# external kicker's staged-prompt shape) and the executor of the wake
# contract's single step. Each unread event is drained exactly once
# (an idempotent row-count cursor over the material row list,
# machine-independent append order) and acted per type through the
# faces that already own each fact. The materiality gate ran BEFORE any
# LLM turn (the watcher is mechanical); a quiet stream drains to a zero
# no-op without calling any face.

#: the drain's cursor state (a runs/scheduler/ sibling of the stream —
#: separate from the watcher's byte cursor; each consumer owns its own).
#: It is THE consumption truth: the watcher seeds its byte cursor from
#: this file on a restart so an already-drained batch is never
#: re-emitted.
DRAIN_STATE_REL = Path("runs") / "scheduler" / "drain-state.json"

#: the mutual-exclusion lock (two concurrent drains must not double-act
#: a batch: the second skips, mirroring the external kicker's lock
#: semantics — a skip is not an error, rc 0)
DRAIN_LOCK_NAME = ".drain.lock"

#: consecutive blocked drains a kind may cause before its rows advance
#: despite the failing face (the poison-row policy: a permanently
#: broken face must not wedge the wake path; the streak clears on the
#: face's first success, so a healed face resumes blocking)
POISON_SKIP_AFTER = 3

#: the per-type action table — kind -> the existing face that acts on
#: that fact (resolved lazily inside each action; one fail-open cage
#: per dispatched type, so one broken face is one warn and the drain
#: never breaks). The mapping targets:
#:   worker-exit       -> the worker reconcile face (ground-truth rebuild)
#:   verdict-landed    -> the verdict-status watch face (diff + emit)
#:   gate-reject       -> the dispatch-reject feedback face (decision feed)
#:   deadline-fired    -> the timer-state read face (per fired rollout)
#:   settle-completed  -> the RL digest emit face (the per-decision line)
def _act_worker_exit(ws, rows) -> dict:
    from reconcile_workers import reconcile_workers
    return {"active": reconcile_workers(ws)}


def _act_verdict_landed(ws, rows) -> dict:
    from verify_status_watch import reconcile
    return reconcile(ws)


def _act_gate_reject(ws, rows) -> dict:
    from rlvr.dispatch_reject import feedback_face
    return feedback_face(ws)


def _act_deadline_fired(ws, rows) -> dict:
    from rlvr import rollout_timer
    states: dict = {}
    for row in rows:
        rid = str(row.get("rollout_id") or "").strip()
        if rid and rid not in states:
            states[rid] = rollout_timer.timer_state(ws, rid)
    return {"rollouts": states}


def _act_settle_completed(ws, rows) -> dict:
    from rl_digest import emit
    return {"digest": emit(ws)}


DRAIN_ACTIONS = {
    "worker-exit": _act_worker_exit,
    "verdict-landed": _act_verdict_landed,
    "gate-reject": _act_gate_reject,
    "deadline-fired": _act_deadline_fired,
    "settle-completed": _act_settle_completed,
}


def _read_drain_state(ws: Path) -> dict:
    """The drain state (cursor + per-kind failure streaks); absent or
    dirty reads the zero face."""
    try:
        doc = json.loads((Path(ws) / DRAIN_STATE_REL)
                         .read_text(encoding="utf-8"))
        rows = max(0, int(doc.get("rows") or 0))
        streaks = {str(k): max(0, int(v))
                   for k, v in (doc.get("fail_streaks") or {}).items()
                   if isinstance(v, (int, float))}
        return {"rows": rows, "fail_streaks": streaks}
    except (OSError, ValueError, TypeError):
        return {"rows": 0, "fail_streaks": {}}


def _write_drain_state(ws: Path, state: dict) -> None:
    """Atomic state write; best-effort — a failed write only re-drains
    (the actions are read/idempotent faces, never a double charge)."""
    p = Path(ws) / DRAIN_STATE_REL
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(p)
    except OSError as exc:
        warn("loop_scheduler.drain_cursor", f"{type(exc).__name__}: {exc}")


def _consume_wake_artifact(ws: Path) -> dict | None:
    """Read-and-clear the staged wake artifact (the delivery consumer's
    exactly-once face): the contract rides the receipt's ``wake`` key,
    the file is unlinked. Absent -> None (quiet — no wake was staged)."""
    p = Path(ws) / "runs" / ".scheduler-wake.json"
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    try:
        p.unlink()
    except OSError as exc:
        warn("loop_scheduler.wake_consume", f"{type(exc).__name__}: {exc}")
    return doc if isinstance(doc, dict) else None


def _acquire_drain_lock(ws: Path):
    """Non-blocking single-instance lock (the watcher's lock shape):
    the fd when acquired, None when another drain holds it — the second
    drain SKIPS (never double-acts), a skip is not an error."""
    import os
    lock_path = Path(ws) / DRAIN_STATE_REL.parent / DRAIN_LOCK_NAME
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    except OSError:
        return None  # uncreatable -> report the skip face, never crash
    try:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except ImportError:
        return fd  # no fcntl: single-writer posture, no lock
    except OSError:
        os.close(fd)
        return None
    try:
        os.write(fd, f"{os.getpid()}\n".encode("utf-8"))
    except OSError as exc:  # noqa: BLE001 — pid stamp is cosmetic
        warn("loop_scheduler.drain_lock", f"pid stamp: {exc}")
    return fd


def _release_drain_lock(fd) -> None:
    import os
    if not isinstance(fd, int):
        return
    try:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)
    except (ImportError, OSError) as exc:  # noqa: BLE001 — best-effort unlock
        warn("loop_scheduler.drain_lock", f"unlock: {exc}")
    try:
        os.close(fd)
    except OSError as exc:  # noqa: BLE001 — best-effort close
        warn("loop_scheduler.drain_lock", f"close: {exc}")


def drain_events(ws) -> dict:
    """Drain the scheduler events stream once: every MATERIAL event past
    the persisted cursor is dispatched per type through DRAIN_ACTIONS
    (the existing faces), then the cursor advances — a second drain over
    the same stream is a zero no-op. Non-material rows are never
    drained (the reader-side closed-vocabulary gate).

    Cursor discipline: the cursor advances only past rows whose kinds
    acted SUCCESSFULLY — a failed kind's earliest row stays below the
    cursor (a prefix advance), so the failed batch retries on the next
    drain instead of being consumed with the action failed. A kind that
    blocks POISON_SKIP_AFTER consecutive drains advances anyway
    (the receipt marks it poisoned) — a permanently broken face must
    not wedge the wake path; the streak clears on the face's first
    success, so a healed face resumes blocking.

    Truncation guard (mirrors the watcher's offset>size reset): a
    rebuilt/pruned stream shorter than the persisted cursor resets the
    cursor to 0 — events are never skipped forever.

    Delivery: the staged wake artifact (runs/.scheduler-wake.json) is
    CONSUMED on every drain-face run — read into the receipt's
    ``wake`` key and unlinked (exactly-once delivery; an unconsumed
    artifact survives a quiet drain for the next one). Mutual
    exclusion: a second concurrent drain skips (``skipped`` receipt)
    without touching cursor or artifact.

    Returns ``{"drained", "attempted", "by_type", "actions", "cursor",
    "wake"}`` (or the skip receipt)."""
    root = Path(ws)  # the CLI's argparse workspace is a plain str:
    lock = _acquire_drain_lock(root)  # coerce ONCE at this boundary
    if lock is None:
        return {"skipped": "lock-held", "drained": 0, "attempted": 0,
                "by_type": {}, "actions": {}, "cursor": None,
                "wake": None}
    try:
        rows_all = scheduler_events.material_rows(root)
        state = _read_drain_state(root)
        cursor = state["rows"]
        if cursor > len(rows_all):
            cursor = 0  # truncation guard: the stream shrank below it
        streaks = dict(state["fail_streaks"])
        pending = rows_all[cursor:]
        wake = _consume_wake_artifact(root)
        if not pending:
            _write_drain_state(root, {"rows": len(rows_all),
                                      "fail_streaks": streaks})
            return {"drained": 0, "attempted": 0, "by_type": {},
                    "actions": {}, "cursor": len(rows_all), "wake": wake}
        by_type: dict[str, list] = {}
        for row in pending:
            by_type.setdefault(str(row.get("kind")), []).append(row)
        actions: dict = {}
        failed_kinds: set[str] = set()
        for kind, rows in sorted(by_type.items()):
            act = DRAIN_ACTIONS.get(kind)
            if act is None:
                continue  # cannot happen (material gate) — belt+braces
            poisoned = streaks.get(kind, 0) >= POISON_SKIP_AFTER
            try:
                actions[kind] = act(root, rows)
                streaks.pop(kind, None)
            except Exception as exc:  # noqa: BLE001 — one face down, drain lives
                warn("loop_scheduler.drain",
                     f"{kind}: {type(exc).__name__}: {exc}")
                entry: dict = {"error": f"{type(exc).__name__}: {exc}"}
                streaks[kind] = streaks.get(kind, 0) + 1
                if poisoned:
                    # the poison policy: advance despite the failure
                    entry["poisoned"] = True
                else:
                    failed_kinds.add(kind)
                actions[kind] = entry
        if failed_kinds:
            first_failed = next(i for i, r in enumerate(pending)
                                if str(r.get("kind")) in failed_kinds)
            new_cursor = cursor + first_failed
        else:
            new_cursor = len(rows_all)
        _write_drain_state(root, {"rows": new_cursor,
                                  "fail_streaks": streaks})
        return {"drained": new_cursor - cursor, "attempted": len(pending),
                "by_type": {k: len(v) for k, v in by_type.items()},
                "actions": actions, "cursor": new_cursor, "wake": wake}
    finally:
        _release_drain_lock(lock)


def interval_to_cron(interval: str = "5m") -> str:
    """`5m` -> `*/5 * * * *`. Supports <60m (`*/N`) and >=60m hourly steps."""
    unit = interval[-1:].lower()
    try:
        n = int(interval[:-1])
    except ValueError as exc:
        raise ValueError(f"unsupported interval {interval!r}") from exc
    if n <= 0:
        raise ValueError(f"non-positive interval {interval!r}")
    if unit == "m" and n < 60:
        return f"*/{n} * * * *"
    if unit == "h" and 0 < n < 24:
        return f"0 */{n} * * *"
    if unit == "m" and n % 60 == 0 and 1 <= n // 60 < 24:
        return f"0 */{n // 60} * * *"
    raise ValueError(
        f"interval {interval!r} has no clean cron expression "
        "(minute steps < 60, hour steps 1-23)")


def scheduled_tasks_path(ws: Path | str) -> Path:
    return Path(ws) / SCHEDULE_FILE_REL


def _backup_bytes(path: Path, raw: bytes, kind: str) -> Path:
    backup = path.with_name(f"{path.name}.{kind}-{int(time.time())}")
    backup.write_bytes(raw)
    return backup


def _read_entries(path: Path) -> tuple[list[dict], Path | None]:
    """Load entries from path; tolerate array / jobs-wrapper / tasks-wrapper
    (#679) / corruption / valid-but-unrecognized shapes.

    Returns (entries, sidecar_path-or-None). NOTHING is ever silently
    clobbered: unreadable bytes AND structurally-valid-but-unknown shapes
    (e.g. {"schedules":[...]}, wrapper objects with sibling keys like
    schemaVersion) are preserved byte-for-byte (*.corrupt-* / *.unrecognized-*)
    before any rebuild happens downstream (r3-M1).
    """
    if not path.exists():
        return [], None
    raw = path.read_bytes()
    try:
        # utf-8-sig: a BOM must not downgrade an otherwise-valid file to corrupt
        data = json.loads(raw.decode("utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return [], _backup_bytes(path, raw, "corrupt")
    if isinstance(data, list):
        return [e for e in data if isinstance(e, dict)], None
    if isinstance(data, dict):
        # jobs first (our container) — a document carrying both keys keeps
        # "tasks" as foreign data that the write path preserves untouched.
        key = next((k for k in ENTRY_KEYS if isinstance(data.get(k), list)),
                   None)
        if key is None:
            return [], _backup_bytes(path, raw, "unrecognized")
        entries = [e for e in data[key] if isinstance(e, dict)]
        if len(data) > 1:
            # sibling keys beside the container (schemaVersion, owner, the
            # other entry key ...) are FOREIGN DATA; belt+braces sidecar even
            # though _write_file now also preserves them in place (r3-M1).
            return entries, _backup_bytes(path, raw, "unrecognized")
        return entries, None
    return [], _backup_bytes(path, raw, "unrecognized")


def _write_file(path: Path, entries: list[dict]) -> None:
    """Write preserving the ORIGINAL document shape (#679).

    A wrapper document keeps its container key — {"tasks": [...]} stays a
    tasks file, {"jobs": [...]} stays a jobs file — and every unknown sibling
    key is carried over in place. Bare arrays stay bare arrays. Fail-open:
    if the prior bytes can't be parsed, fall back to the wrapper detection
    below (head starts with "{") so a corrupt file still rebuilds as before.
    """
    payload: object = entries
    if path.exists():
        head = path.read_text(encoding="utf-8", errors="replace").strip()
        try:
            data = json.loads(path.read_bytes().decode("utf-8-sig"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            data = None
        if isinstance(data, dict):
            # same container choice as _read_entries: first known key whose
            # value is actually a list (jobs preferred), else first known key
            # present, else default "jobs" (add ours, keep every sibling).
            key = next((k for k in ENTRY_KEYS
                        if isinstance(data.get(k), list)), None)
            if key is None:
                key = next((k for k in ENTRY_KEYS if k in data), "jobs")
            rebuilt = {k: (entries if k == key else v)
                       for k, v in data.items()}
            if key not in data:      # no known container -> add ours, keep rest
                rebuilt[key] = entries
            payload = rebuilt
        elif isinstance(data, list):
            payload = entries
        elif head.startswith("{"):
            payload = {"jobs": entries}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(path)


def _is_our_entry(entry: dict, ws_str: str) -> bool:
    """Identity rule for the kunglao loop entry: our id, or (belt+braces) a
    foreign-id entry whose prompt unmistakably carries OUR loop body + ws."""
    if entry.get("id") == JOB_ID:
        return True
    prompt = entry.get("prompt") or ""
    return (JOB_NAME in prompt or all(m in prompt for m in PROMPT_MARKERS)) \
        and ws_str in prompt


def find_loop_entry(entries: list[dict], ws: Path | str) -> dict | None:
    ws_str = str(Path(ws))
    for e in entries:
        if _is_our_entry(e, ws_str):
            return e
    return None


def loop_entry_exists(ws: Path | str) -> bool:
    entries, _ = _read_entries(scheduled_tasks_path(ws))
    return find_loop_entry(entries, ws) is not None


def upsert_durable_loop(ws: Path | str, interval: str = "5m") -> int:
    """Idempotently register/renew the durable /loop entry. Returns rc.

    Replaces OUR entry by identity (never stacks a duplicate); foreign
    entries are untouched. The prompt body comes from the emitter
    (heartbeat_loop_prompt.build_prompt) — never a re-embedded copy (#598).
    """
    from heartbeat_loop_prompt import build_prompt

    ws_path = Path(ws).resolve()
    path = scheduled_tasks_path(ws_path)
    entries, corrupt_backup = _read_entries(path)

    prompt_body = build_prompt(str(ws_path), interval)
    ours = {
        "id": JOB_ID,
        "name": JOB_NAME,
        "cron": interval_to_cron(interval),
        "prompt": prompt_body,
        "durable": True,
        "createdAt": utc_now(),
    }
    ws_str = str(ws_path)
    kept, replaced = [], False
    for e in entries:
        if not replaced and _is_our_entry(e, ws_str):
            # preserve foreign fields we don't own? No — the canonical shape
            # above IS the contract for our id; stale foreign additions die.
            kept.append(ours)
            replaced = True
        elif _is_our_entry(e, ws_str):
            pass  # extra legacy duplicate of ours — drop (dedup)
        else:
            kept.append(e)
    if not replaced:
        kept.append(ours)
    _write_file(path, kept)
    detail = f"{path} ({ours['cron']}, durable)"
    if corrupt_backup:
        print(f"loop_scheduler: prior schedule file was unreadable/unrecognized "
              f"- original preserved at {corrupt_backup} (r3-M1: never a "
              f"silent clobber)", file=sys.stderr)
    print(f"OK: durable /loop registered/updated at {detail}")
    print("NOTE: Claude Code caps durable schedules at 7 days - re-run "
          "/kunglao-agent:init (or recreate the schedule) when it expires.")
    return 0


def remove_durable_loop(ws: Path | str) -> int:
    """#638: the sanctioned REMOVAL face for our durable loop entry.

    Cancelling the loop previously required hand-editing
    scheduled_tasks.json: CronDelete cannot remove a loop_scheduler-written
    entry (it was never armed in the runtime), and this module had upsert
    only. Idempotent: no entry -> "nothing to remove", rc 0. Foreign
    entries are never touched."""
    path = scheduled_tasks_path(ws)
    entries, corrupt_backup = _read_entries(path)
    kept = [e for e in entries if e.get("id") != JOB_ID]
    removed = len(entries) - len(kept)
    if corrupt_backup:
        print(f"loop_scheduler: prior schedule file was unreadable/"
              f"unrecognized - original preserved at {corrupt_backup}",
              file=sys.stderr)
    if removed:
        _write_file(path, kept)
        print(f"OK: durable /loop entry removed from {path} "
              f"({removed} entr{'y' if removed == 1 else 'ies'} removed, "
              f"{len(kept)} left)")
    else:
        print(f"OK: no durable /loop entry at {path} - nothing to remove")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="loop_scheduler.py",
                                 description="durable /loop registration")
    ap.add_argument("workspace")
    ap.add_argument("--interval", default="5m")
    ap.add_argument("--check", action="store_true",
                    help="rc0 when the entry exists, rc2 when missing (no write)")
    ap.add_argument("--remove", action="store_true",
                    help="#638: remove OUR durable entry (idempotent; "
                         "foreign entries untouched)")
    ap.add_argument("--drain-events", action="store_true",
                    help="drain the scheduler events stream once (the "
                         "event-driven wake path's session-side half): "
                         "each unread material event is dispatched per "
                         "type through the existing faces; prints the "
                         "drain receipt JSON")
    args = ap.parse_args(argv)
    if args.check:
        return 0 if loop_entry_exists(args.workspace) else 2
    if args.remove:
        return remove_durable_loop(args.workspace)
    if args.drain_events:
        import json as _json
        print(_json.dumps(drain_events(args.workspace), ensure_ascii=False,
                          indent=2))
        return 0
    return upsert_durable_loop(args.workspace, args.interval)


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())
