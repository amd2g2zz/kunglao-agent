# -*- coding: utf-8 -*-
"""cost_gate.py - detect cost warnings and emit advisory or hard-pause.

User pain point: "PostToolUse hook cost warnings interrupt kunglao-agent workflow."

kunglao-agent's orchestrator loop is long-horizon; one cost warning from Claude Code's
PostToolUse hook (e.g. "COST WARNING: session total ~$NN") does NOT mean the user
wants kunglao-agent to abort. But repeated warnings or single warning + high absolute
cost SHOULD trigger an advisory.

This script:
  - Reads the settlement family's cost-event rows (runs/settlement.jsonl,
    schema ``cost-event/1`` — the #1004 consolidation home; the standalone
    cost-events file rel is retired) written by the PostToolUse hook when
    "COST WARNING" is detected
  - Counts warnings in last N minutes (sliding window)
  - Tiered response:
      * 1 warning: emit advisory "advisory: reduce dispatch verbosity"
      * 2 warnings within 10 min: "advisory: pause non-essential hooks"
      * cost is INFORMATIONAL only (user ruling): advisory output, never gates dispatch
        must complete current iteration then ask user before next"
  - Writes cost_advice.json with current tier (consumed by orchestrator)
  - Exits 0 always (advisory is non-fatal); hard-pause is signaled via JSON + exit 2

Hook wire-up (NOT auto-installed by this script - kunglao-agent hooks are selective
per F-10 / hook_activation.py):
  - PostToolUse on Edit|Write|MultiEdit|Agent: matches "COST WARNING" in tool_result
  - Appends one cost-event/1 row per warning (consolidated settlement file)
  - This script reads the cost face on heartbeat tick

Usage:
  python cost_gate.py <workspace> [--window-min 10] [--hard-cap 50.0]
Exit codes:
  0 = normal (no action)
  1 = advisory emitted
  1 = ADVISORY (informational); never blocks dispatch (user ruling)
"""
from __future__ import annotations
import hook_activation as ha


import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from harness_common import utc_now  # #863 Family F: single source (was a local def)
from kunglao_log import iter_jsonl  # noqa: E402  (#863 Family K single source)
from rlvr import consolidated_ledger as _cl  # noqa: E402  (#1004 family face)

#: the cost telemetry's registered stamp (the settlement family's cost face)
COST_SCHEMA = "cost-event/1"
COST_ADVICE_FILE = "cost_advice.json"


def parse_event(line_or_row) -> dict | None:
    """Validate one cost-event/1 row: {"ts": ISO, "amount": number, ...}
    (accepts a raw JSONL line string or an already-parsed row)."""
    row = line_or_row
    if isinstance(row, str):
        row = next(iter_jsonl([row]), None)
    if not isinstance(row, dict) or "ts" not in row or "amount" not in row:
        return None
    return row


def load_events(workspace: Path) -> list:
    """Load all cost events from the settlement family's cost face."""
    out = []
    for ev in _cl.read(workspace, "settlement", schema_prefix=COST_SCHEMA):
        if parse_event(ev) is None:
            continue
        try:
            ev["dt"] = datetime.fromisoformat(
                str(ev["ts"]).replace("Z", "+00:00"))
        except ValueError:
            continue
        out.append(ev)
    return out


def write_advice(workspace: Path, tier: str, count: int, latest_amount: float) -> None:
    advice = {
        "ts": utc_now().isoformat().replace("+00:00", "Z"),
        "tier": tier,
        "warning_count_window": count,
        "latest_amount_usd": latest_amount,
        "action": {
            "advisory": "reduce dispatch verbosity; prefer T1/T2 over T3",
            "pause_non_essential": "suspend non-essential hooks (reuse/troubleshooting/search); keep active_intervention.py + cost_gate",
        }.get(tier, "no action"),
    }
    path = workspace / COST_ADVICE_FILE
    path.write_text(json.dumps(advice, indent=2, ensure_ascii=False), encoding="utf-8")


def check(workspace: Path, window_min: int, hard_cap: float) -> int:
    events = load_events(workspace)
    if not events:
        # No events file = no warnings. Exit 0 normally.
        if (workspace / COST_ADVICE_FILE).exists():
            (workspace / COST_ADVICE_FILE).unlink()
        return 0

    now = utc_now()
    cutoff = now - timedelta(minutes=window_min)
    in_window = [e for e in events if e["dt"] >= cutoff]
    count = len(in_window)
    latest = events[-1]
    latest_amount = float(latest.get("amount", 0.0))

    # Cost is INFORMATIONAL, never a stop reason (user ruling 2026-08-06).
    # HARD_PAUSE / pause_non_essential removed — cost never gates dispatch.
    if count >= 1 or latest_amount >= hard_cap:
        tier = "advisory"
    else:
        tier = "none"

    write_advice(workspace, tier, count, latest_amount)

    if tier == "advisory":
        print(f"ADVISORY: cost={count} warnings in {window_min}m, latest=${latest_amount:.2f} (informational only)")
        return 1

    print(f"OK: cost within bounds ({count} warnings in {window_min}m, latest=${latest_amount:.2f})")
    return 0


def append_event(workspace: Path, amount: float, source: str = "hook") -> None:
    """Helper for hook to append a new cost event (cost-event/1, the
    settlement family's consolidated file). Used by PostToolUse hook.
    Fail-open: the consolidated append refuses loudly (ONE warn) and
    never raises into the hook."""
    ev = {
        "schema": COST_SCHEMA,
        "ts": utc_now().isoformat().replace("+00:00", "Z"),
        "amount": amount,
        "source": source,
    }
    _cl.append(workspace, "settlement", ev)


def main() -> int:
    parser = argparse.ArgumentParser(description="Cost gate advisory + hard-pause")

    parser.add_argument("workspace", help="workspace root")
    parser.add_argument("--window-min", type=int, default=10,
                        help="sliding window in minutes (default 10)")
    parser.add_argument("--hard-cap", type=float, default=50.0,
                        help="absolute USD cap; latest_amount >= this shows advisory (never gates dispatch)")
    parser.add_argument("--append-event", type=float, default=None,
                        help="if set, append a cost event with this amount instead of checking")
    parser.add_argument("--source", default="hook", help="source tag for --append-event")
    args = parser.parse_args()

    # F-10 selective activation: skip if hook is paused
    if not ha.is_active_strict(Path(args.workspace), "cost_gate"):
        print("SKIP: cost_gate is paused (check .hook_state.json)")
        return 0

    workspace = Path(args.workspace)
    if args.append_event is not None:
        append_event(workspace, args.append_event, args.source)
        print(f"appended cost event: ${args.append_event:.2f} from {args.source}")
        return 0

    return check(workspace, window_min=args.window_min, hard_cap=args.hard_cap)


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())