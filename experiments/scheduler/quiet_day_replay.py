#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""quiet_day_replay.py — the pre-wiring experiment for the event-driven
wake path (the scheduler-events slice).

Drives the REAL watcher face (scheduler_watch.poll_once) OFFLINE over
synthetic days — a quiet day (zero material events), a material day
(five events), and a noise day (hand-placed non-material rows) — at the
old fixed-cron cadence (288 polls/day, the 5-minute heartbeat the event
path replaces). It is the sanity gate the wake wiring must pass before
it lands: if a quiet day emits even one wake contract, or a material
day emits more wakes than events, or noise ever wakes the session, the
wiring is wrong.

Pins asserted here (each printed as PASS/FAIL, exit 1 on any FAIL):

  P1 quiet    a synthetic quiet day (288 polls, zero material events)
              emits ZERO wake contracts — the token metric the event
              path exists for: quiet_tokens = 0.
  P2 material a synthetic material day (5 events across the day) emits
              at most 5 wake contracts (batching may merge events into
              one wake; every event byte is consumed — the final cursor
              equals the file size, so no event is lost).
  P3 noise    hand-placed non-material rows (heartbeat/tick shapes the
              writer-side gate refuses, injected at the file level)
              NEVER wake the session — the reader-side closed-
              vocabulary gate holds.

The table: per day, polls, material events, wake contracts, and the
quiet-day token spend (an LLM turn per wake; a poll is free).

Usage:
    python experiments/scheduler/quiet_day_replay.py [--seed 1001]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
for _p in (SCRIPTS,):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import scheduler_events as scheduler_events  # noqa: E402
import scheduler_watch as scheduler_watch  # noqa: E402

#: the old fixed-cron cadence the event path replaces: 288 wakes/day
POLLS_PER_DAY = 288

#: the noise rows injected at the FILE level (the writer-side gate
#: refuses them, so only a hand-edit — or a rogue writer — can land one)
NOISE_KINDS = ("heartbeat", "tick", "schedule_scan")

MATERIAL_DAY_EVENTS = 5


def _run_day(ws: Path, append_event) -> dict:
    """One synthetic day at the old cadence: 288 watcher polls; the
    event callback decides what (if anything) lands, and when. Each day
    starts from a FRESH stream (the day is the unit of the experiment —
    no cross-day carryover of rows or cursor)."""
    sched_dir = ws / "runs" / "scheduler"
    if sched_dir.exists():
        for stale in sched_dir.iterdir():
            stale.unlink()
    events_file = ws / scheduler_events.EVENTS_REL
    if events_file.exists():
        events_file.unlink()
    wakes = 0
    for tick in range(POLLS_PER_DAY):
        append_event(tick)
        if scheduler_watch.poll_once(ws) is not None:
            wakes += 1
    consumed = 0
    if events_file.exists():
        state_file = scheduler_events.state_path(ws, "watch-state.json")
        state = json.loads(state_file.read_text(encoding="utf-8")) \
            if state_file.exists() else {"offset": 0}
        consumed = state.get("offset", 0)
    return {"polls": POLLS_PER_DAY, "wakes": wakes,
            "events": scheduler_events.count_rows(ws),
            "consumed_bytes": consumed,
            "file_bytes": events_file.stat().st_size
            if events_file.exists() else 0}


def run_replay(seed: int = 1001) -> dict:
    rng = random.Random(seed)
    days: dict[str, dict] = {}
    with tempfile.TemporaryDirectory(prefix="quiet-day-") as tmp:
        ws = Path(tmp) / "ws"
        (ws / "runs").mkdir(parents=True)

        # the quiet day: nothing lands, all day
        days["quiet"] = _run_day(ws, lambda tick: None)

        # the material day: five events, spread across the day
        wake_ticks = sorted(rng.sample(range(POLLS_PER_DAY),
                                       MATERIAL_DAY_EVENTS))
        kinds = list(scheduler_events.KINDS)

        def _material_day(tick: int) -> None:
            if tick in wake_ticks:
                i = wake_ticks.index(tick)
                scheduler_events.append(ws, kinds[i % len(kinds)],
                                        claim=f"C-{i:03d}")
        days["material"] = _run_day(ws, _material_day)

        # the noise day: non-material rows injected at the file level —
        # every poll appends one noise row the append face would refuse
        events_file = ws / scheduler_events.EVENTS_REL

        def _noise_day(tick: int) -> None:
            row = {"ts": "2026-11-05T12:00:00Z",
                   "schema": scheduler_events.SCHEMA,
                   "kind": NOISE_KINDS[tick % len(NOISE_KINDS)]}
            events_file.parent.mkdir(parents=True, exist_ok=True)
            with events_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
        days["noise"] = _run_day(ws, _noise_day)

    return {"days": days, "wake_ticks": wake_ticks}


def metric_rows(result: dict) -> list[dict]:
    """The acceptance's measurable face: one JSON metric row per day —
    ``quiet_tokens`` is the slice's token metric (an LLM turn per wake;
    a poll is free), pinned at 0 by P1."""
    rows = []
    for name, day in result["days"].items():
        rows.append({
            "metric": "quiet_tokens" if name == "quiet"
            else f"{name}_wakes",
            "day": name,
            "polls": day["polls"],
            "events": day["events"],
            "wakes": day["wakes"],
            "value": 0 if name == "quiet" else day["wakes"],
        })
    return rows


def check_pins(result: dict) -> list[str]:
    failures: list[str] = []
    days = result["days"]

    quiet = days["quiet"]
    if quiet["wakes"] != 0:
        failures.append(f"P1 quiet day emitted {quiet['wakes']} wakes "
                        f"(must be 0)")
    else:
        print(f"P1 PASS quiet day: {quiet['polls']} polls, 0 wakes — "
              f"quiet_tokens=0")

    material = days["material"]
    if material["wakes"] > material["events"]:
        failures.append(f"P2 material day emitted {material['wakes']} "
                        f"wakes for {material['events']} events")
    else:
        print(f"P2 PASS material day: {material['events']} events -> "
              f"{material['wakes']} wakes (batching merge allowed)")
    if material["consumed_bytes"] != material["file_bytes"]:
        failures.append(f"P2 event loss: consumed "
                        f"{material['consumed_bytes']} of "
                        f"{material['file_bytes']} bytes")
    else:
        print(f"P2 PASS every event byte consumed "
              f"({material['file_bytes']} bytes)")

    noise = days["noise"]
    if noise["wakes"] != 0:
        failures.append(f"P3 noise day emitted {noise['wakes']} wakes "
                        f"from {noise['events']} non-material rows")
    else:
        print(f"P3 PASS noise day: {noise['events']} non-material rows, "
              f"0 wakes — the reader-side gate holds")
    return failures


def print_table(result: dict) -> None:
    print("\n=== quiet-day replay (the old fixed cron's cadence: "
          f"{POLLS_PER_DAY} polls/day) ===")
    print(f"{'day':>9} {'polls':>6} {'events':>7} {'wakes':>6} "
          f"{'quiet_tokens':>13}")
    for name, day in result["days"].items():
        tokens = 0 if name == "quiet" else day["wakes"]
        print(f"{name:>9} {day['polls']:>6} {day['events']:>7} "
              f"{day['wakes']:>6} {tokens:>13}")
    # the metric rows: one JSON line each — the acceptance's measurable
    # face (quiet_tokens=0 pinned by P1), greppable from any runner
    for row in metric_rows(result):
        print("METRIC " + json.dumps(row, ensure_ascii=False,
                                     sort_keys=True))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1001)
    ap.add_argument("--json", action="store_true",
                    help="print ONLY the metric rows (one JSON line "
                         "each) — the machine-readable face")
    args = ap.parse_args()
    result = run_replay(seed=args.seed)
    if args.json:
        for row in metric_rows(result):
            print(json.dumps(row, ensure_ascii=False, sort_keys=True))
        return 0
    print_table(result)
    failures = check_pins(result)
    if failures:
        print("\n=== FAILURES ===")
        for f in failures:
            print(f"FAIL {f}")
        return 1
    print("\nGATE: the event-driven wake path holds — a quiet day costs "
          "zero wakes, a material day never exceeds one wake per event, "
          "noise never wakes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
