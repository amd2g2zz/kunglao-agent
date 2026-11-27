#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rollout_timer_wake.py — the one-shot deadline wake's executor.

The orchestrator creates the timer's one-shot cron from the wake
contract the dispatch-commit face published
(``runs/rollout-timer-wake.json``). THIS command is what the wake runs:
fire the deadline, record the settlement-facing deadline stop, cancel
the timer, learn the timeout, and print the receipt with the
graceful-stop contract (the wrap-up prompt included). It NEVER starts a
rollout — the contract's only steps are persist, settle, cancel, learn,
arm-next.

Usage:
    python scripts/rollout_timer_wake.py <WORKSPACE> --wake <rollout_id>
        [--now <YYYY-MM-DDTHH:MM:SSZ>]

Exit codes: 0 the deadline fired (receipt JSON on stdout); 3 the wake
was refused (not yet due / already canceled / unknown rollout — nothing
to wrap up); 2 usage error. A refused wake is never a crash: the cron
wake cannot force-fire a timer the loop already closed.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rlvr import rollout_timer  # noqa: E402
from rlvr import rollout_timer_host  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Run the one-shot rollout deadline wake (fire, record "
                    "the stop, cancel, learn — never start a rollout).")
    ap.add_argument("workspace", help="the analysis workspace root")
    ap.add_argument("--wake", required=True, help="the rollout id to fire")
    ap.add_argument("--now", default=None,
                    help="override the clock (ISO UTC, for replay/tests)")
    args = ap.parse_args()
    when = None
    if args.now:
        try:
            when = datetime.strptime(args.now, rollout_timer._TS_FORMAT) \
                .replace(tzinfo=timezone.utc)
        except ValueError:
            print(f"--now must be ISO UTC ({rollout_timer._TS_FORMAT}): "
                  f"got {args.now!r}", file=sys.stderr)
            return 2
    receipt = rollout_timer_host.deadline_wake_face(args.workspace,
                                                    args.wake, now=when)
    if receipt is None:
        print(f"deadline wake refused for {args.wake!r} "
              "(not due, canceled, or unknown — nothing to wrap up)",
              file=sys.stderr)
        return 3
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
