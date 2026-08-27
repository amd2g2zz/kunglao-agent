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

Reader tolerates three shapes of an existing file:
  [entry, ...]                 bare array
  {"jobs": [entry, ...]}       wrapper object
  corrupt bytes                backed up to *.corrupt-<ts> then rebuilt

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
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

JOB_ID = "kunglao-heartbeat"
JOB_NAME = "kunglao-agent heartbeat"
PROMPT_MARKERS = ("kunglao-agent heartbeat", "--heartbeat-on")

SCHEDULE_FILE_REL = Path(".claude") / "scheduled_tasks.json"


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
    """Load entries from path; tolerate array / jobs-wrapper / corruption /
    valid-but-unrecognized shapes.

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
        jobs = data.get("jobs")
        recognized = isinstance(jobs, list)
        if recognized and len(data) > 1:
            # sibling keys beside "jobs" (schemaVersion etc.) are FOREIGN DATA;
            # flattening them into our rewrite loses bytes -> preserve first.
            return ([e for e in jobs if isinstance(e, dict)],
                    _backup_bytes(path, raw, "unrecognized"))
        if recognized:
            return [e for e in jobs if isinstance(e, dict)], None
        return [], _backup_bytes(path, raw, "unrecognized")
    return [], _backup_bytes(path, raw, "unrecognized")


def _write_file(path: Path, entries: list[dict]) -> None:
    """Write preserving the WRAPPER shape when the original had one."""
    was_wrapper = False
    if path.exists():
        head = path.read_text(encoding="utf-8", errors="replace").strip()
        was_wrapper = head.startswith("{")
    payload = {"jobs": entries} if was_wrapper else entries
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="loop_scheduler.py",
                                 description="durable /loop registration")
    ap.add_argument("workspace")
    ap.add_argument("--interval", default="5m")
    ap.add_argument("--check", action="store_true",
                    help="rc0 when the entry exists, rc2 when missing (no write)")
    args = ap.parse_args(argv)
    if args.check:
        return 0 if loop_entry_exists(args.workspace) else 2
    return upsert_durable_loop(args.workspace, args.interval)


if __name__ == "__main__":
    sys.exit(main())
