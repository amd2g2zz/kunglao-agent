# -*- coding: utf-8 -*-
"""feedback.py — subagent feedback inbox + triage + stale detection (#241).

Subagent feedback is part of the environment: a worker/verifier report that
contradicts, extends, or challenges the plan is neither blindly obeyed (a
challenge is not a verdict) nor blindly ignored (an env_alert is a mechanical
signal, not a discussion topic). The pipeline:

  enqueue(entry)     append {id, source, ts, type, claim_id, summary,
                            status: NEW} to the append-only inbox, then
                            classify() it (disposition persisted with entry)
  classify(entry)    env_alert -> mechanical signal, straight through
                     (needs_verify: False); every other type -> the claim
                     position must be re-derived by an independent verifier
                     (redteam) before it can move the loop (needs_verify:
                     True) — accept as hypothesis, artifact judges truth
  check_stale()      entries still NEW after > max_ticks heartbeat ticks
                     (35 min per tick, matching hook_activation's heartbeat
                     liveness window) -> alarm list, so an unanswered
                     challenge never sits in the inbox forever. Integration
                     into heartbeat_tick.py lands with #237 — this module is
                     standalone and unit-tested.

Inbox file: <ws>/runs/feedback-inbox.yaml — a YAML list, append-only.

Usage:
  python feedback.py <workspace> enqueue '<json>'
  python feedback.py <workspace> list
  python feedback.py <workspace> dispose '<json>'    # {"index": N} | {"id": ...}
  python feedback.py <workspace> stale [--max-ticks N]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

FEEDBACK_TYPES = ("blocker", "discovery", "refutation", "env_alert", "challenge")
INBOX_NAME = "feedback-inbox.yaml"
# One heartbeat tick window, matching hook_activation's heartbeat liveness
# check ("< 35 min old"): an entry untouched for more than max_ticks such
# windows has survived that many ticks without the loop acting on it.
TICK_INTERVAL_MIN = 35
DEFAULT_MAX_TICKS = 3


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_inbox(inbox: Path) -> list:
    if not inbox.exists():
        return []
    try:
        data = yaml.safe_load(inbox.read_text(encoding="utf-8")) or []
    except yaml.YAMLError:
        return []
    return data if isinstance(data, list) else []


def classify(entry: dict) -> dict:
    """Pure triage: env_alert is a mechanical signal (straight through);
    every other type needs an independent redteam verify before it can move
    the loop. Returns a NEW dict — input is not mutated (immutable pattern).
    """
    out = dict(entry)
    out["needs_verify"] = entry.get("type") != "env_alert"
    return out


def enqueue(inbox: Path, entry: dict) -> dict:
    """Append a NEW feedback entry and persist its classification.

    Raises ValueError for unknown feedback types (fail fast at the system
    boundary — a typo'd type must not silently join the inbox).
    """
    if entry.get("type") not in FEEDBACK_TYPES:
        raise ValueError(
            f"unknown feedback type {entry.get('type')!r}; "
            f"expected one of {FEEDBACK_TYPES}"
        )
    inbox.parent.mkdir(parents=True, exist_ok=True)
    entry = classify(entry)
    entry.setdefault("id", f"fb-{utc_now()}-{len(read_inbox(inbox)) + 1}")
    entry.setdefault("ts", utc_now())
    entry.setdefault("status", "NEW")
    entries = read_inbox(inbox)
    entries.append(entry)
    inbox.write_text(
        yaml.safe_dump(entries, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return entry


def dispose(inbox: Path, selector: dict) -> bool:
    """Mark the selected NEW entry DISPOSED (by {"index": N} or {"id": ...}).

    Returns True when an entry was disposed. Disposal records the loop's
    answer — a DISPOSED entry is never stale-alarmed again.
    """
    entries = read_inbox(inbox)
    idx = selector.get("index")
    if idx is None:
        target_id = selector.get("id")
        idx = next((i for i, e in enumerate(entries) if e.get("id") == target_id), None)
    if idx is None or not (0 <= idx < len(entries)):
        return False
    entries[idx]["status"] = "DISPOSED"
    inbox.write_text(
        yaml.safe_dump(entries, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return True


def check_stale(inbox: Path, max_ticks: int = DEFAULT_MAX_TICKS,
                now: datetime | None = None) -> list:
    """NEW entries that survived > max_ticks heartbeat ticks -> alarm list.

    Age is measured against the entry's enqueue ts; one tick is
    TICK_INTERVAL_MIN long. An empty or missing inbox returns [] (no false
    alarm); unparseable timestamps are skipped, not crashed on.
    """
    if not inbox.exists():
        return []
    now = now or datetime.now(timezone.utc)
    alarms = []
    for e in read_inbox(inbox):
        if (e.get("status") or "").upper() != "NEW":
            continue
        try:
            ts_parsed = datetime.strptime(e["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        age_min = (now - ts_parsed).total_seconds() / 60.0
        if age_min > max_ticks * TICK_INTERVAL_MIN:
            alarms.append(e)
    return alarms


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description="Feedback inbox + triage")
    parser.add_argument("workspace", help="workspace root")
    parser.add_argument("command", choices=("enqueue", "list", "dispose", "stale"))
    parser.add_argument("payload", nargs="?", default=None,
                        help="JSON string (enqueue entry / dispose selector)")
    parser.add_argument("--max-ticks", type=int, default=DEFAULT_MAX_TICKS,
                        help=f"stale threshold in heartbeat ticks (default {DEFAULT_MAX_TICKS})")
    args = parser.parse_args(argv)

    inbox = Path(args.workspace) / "runs" / INBOX_NAME

    if args.command == "enqueue":
        if not args.payload:
            parser.error("enqueue requires a JSON payload")
        try:
            entry = json.loads(args.payload)
        except json.JSONDecodeError as exc:
            parser.error(f"enqueue payload is not valid JSON: {exc}")
        saved = enqueue(inbox, entry)
        print(f"feedback: enqueued {saved['id']} type={saved['type']} "
              f"claim_id={saved.get('claim_id')} needs_verify={saved['needs_verify']}")
        return 0

    if args.command == "list":
        for i, e in enumerate(read_inbox(inbox)):
            print(f"  [{i}] {e.get('status')} {e.get('type')} "
                  f"claim_id={e.get('claim_id')} needs_verify={e.get('needs_verify')} "
                  f"| {e.get('summary')}")
        return 0

    if args.command == "dispose":
        try:
            selector = json.loads(args.payload or "{}")
        except json.JSONDecodeError as exc:
            parser.error(f"dispose payload is not valid JSON: {exc}")
        return 0 if dispose(inbox, selector) else 1

    # stale
    stale = check_stale(inbox, max_ticks=args.max_ticks)
    for e in stale:
        print(f"STALE-FEEDBACK {e.get('id')} claim_id={e.get('claim_id')} "
              f"source={e.get('source')} | {e.get('summary')}")
    return 1 if stale else 0


if __name__ == "__main__":
    from utf8_boot import force_utf8  # #811 入口 UTF-8 保险
    force_utf8()
    sys.exit(main())
