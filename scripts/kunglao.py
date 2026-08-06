#!/usr/bin/env python3
"""kunglao.py — kunglao-agent unified entry point (Phase 3 E3.1).

Replaces the 31 scattered CLIs with subcommands, each composing existing
script pure functions. Output contract (JSON + exit codes) is FROZEN to
match the legacy scripts — worker_pulse.py parses convergence_check --json
and priority --json via subprocess, so byte-identical output is mandatory.

E3.1 criteria: kunglao.py decide <ws> --json == convergence_check.py <ws> --json
(byte-identical diff on same fixture).

Subcommands (Phase 3, first wave):
  decide    <- convergence_check.decide (M1)
  tick      <- heartbeat_tick chain (M5, E3.2)
  verify    <- (M3, next)
  record    <- (M4, next)
  health    <- convergence_health (M5)

Usage:
    python kunglao.py decide <workspace> --json
    python kunglao.py health <workspace>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import convergence_check as cc
import heartbeat_tick as hbt


def cmd_decide(args) -> int:
    ws = Path(args.workspace).resolve()
    if args.json:
        # Legacy contract: convergence_check --json emits decision dict + exit code
        d = cc.decide(ws)
        print(json.dumps(d, ensure_ascii=False, indent=2))
        return d["exit_code"]
    return cc.main()


def cmd_tick(args) -> int:
    """M5 tick: heartbeat_tick chain (selfcheck/reconcile/renew/heartbeat-check).
    E3.2: output must match legacy heartbeat_tick.py chain."""
    ws = Path(args.workspace).resolve()
    return hbt.main() if hasattr(hbt, "main") else 0


def cmd_health(args) -> int:
    import convergence_health as ch
    ws = Path(args.workspace).resolve()
    return ch.main() if hasattr(ch, "main") else 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="kunglao.py", description="kunglao-agent unified entry")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_decide = sub.add_parser("decide", help="convergence decision (M1)")
    p_decide.add_argument("workspace", nargs="?", default=".")
    p_decide.add_argument("--json", action="store_true")
    p_decide.set_defaults(func=cmd_decide)

    p_tick = sub.add_parser("tick", help="heartbeat tick chain (M5)")
    p_tick.add_argument("workspace", nargs="?", default=".")
    p_tick.set_defaults(func=cmd_tick)

    p_health = sub.add_parser("health", help="convergence health (M5)")
    p_health.add_argument("workspace", nargs="?", default=".")
    p_health.set_defaults(func=cmd_health)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
