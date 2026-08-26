#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
  verify    <- kunglao_verify.main (M3)
  record    <- kunglao_record.main (M4)
  health    <- convergence_health (M5)
  resume    <- kunglao_resume.main (#466 crash/reboot brief, read-only)

Usage:
    python kunglao.py decide <workspace> --json
    python kunglao.py verify <workspace> <fact_id> [--json]
    python kunglao.py record <workspace> --event '<json>'
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
    # Human mode: render cc.decide() via convergence_check's own _human —
    # never call cc.main(), whose argparse would re-parse the ROUTER's argv
    # (["decide", <ws>]) and SystemExit 2 (issue #370).
    d = cc.decide(ws)
    print(cc._human(d))
    return d["exit_code"]


def cmd_tick(args) -> int:
    """M5 tick: heartbeat_tick chain (selfcheck/reconcile/renew/heartbeat-check).
    E3.2: output must match legacy heartbeat_tick.py chain."""
    ws = Path(args.workspace).resolve()
    # Explicit argv injection (issue #370): a bare hbt.main() read sys.argv[1],
    # i.e. the router's subcommand token "tick", as the workspace path.
    return hbt.main([str(ws)])


def cmd_verify(args) -> int:
    """M3 VERIFY: delegate to kunglao_verify.main (L1 mechanical + L2 redteam)."""
    import kunglao_verify as kv
    argv = [str(args.workspace)]
    if args.fact_id:
        argv.append(args.fact_id)
    if args.json:
        argv.append("--json")
    if args.grace:
        argv.append("--grace")
    if args.grace_scan:
        argv.append("--grace-scan")
    return kv.main(argv)


def cmd_record(args) -> int:
    """M4 RECORD: delegate to kunglao_record.main (ledger idempotent append)."""
    import kunglao_record as kr
    argv = [str(args.workspace)]
    if args.event:
        argv += ["--event", args.event]
    if args.claim_migrate:
        argv += ["--claim-migrate"] + args.claim_migrate
    if args.read is not None:
        argv += ["--read", args.read] if args.read else ["--read"]
    return kr.main(argv)


def cmd_health(args) -> int:
    """M5 health: compose convergence_health's module functions directly —
    never ch.main(), whose argparse would re-parse the ROUTER's argv
    (["health", <ws>]) and SystemExit 2 (issue #370)."""
    import convergence_health as ch
    ws = Path(args.workspace).resolve()
    ledger = ch._read_ledger(ws)
    if not ledger:
        print(f"FAIL: no {ch.LEDGER_NAME} under {ws} (run convergence_check.py first)",
              file=sys.stderr)
        return ch.EXIT_NO_DATA
    r = ch.assess(ledger)
    print(ch._human(r))
    return r["exit_code"]


def cmd_resume(args) -> int:
    """#466: crash/reboot recovery brief — pure delegation to
    kunglao_resume.main (READ-ONLY: decide() direct, never cc.main())."""
    import kunglao_resume as kresume
    argv = [str(args.workspace)]
    if args.json:
        argv.append("--json")
    return kresume.main(argv)


def cmd_upgrade(args) -> int:
    """#726: workspace framework-scaffold migration — pure delegation to
    kunglao_upgrade.main. Hyphenated filename blocks a plain import; the
    module is loaded via importlib (same pattern the test suite uses for
    kunglao-init)."""
    import importlib.util
    mod_path = Path(__file__).resolve().parent / "kunglao_upgrade.py"
    spec = importlib.util.spec_from_file_location("kunglao_upgrade", mod_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    argv = [str(args.workspace)]
    if args.dry_run:
        argv.append("--dry-run")
    return mod.main(argv)


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

    p_verify = sub.add_parser("verify", help="M3 VERIFY (L1 mechanical + L2 redteam)")
    p_verify.add_argument("workspace", nargs="?", default=".")
    p_verify.add_argument("fact_id", nargs="?", default=None)
    p_verify.add_argument("--json", action="store_true")
    p_verify.add_argument("--grace", action="store_true",
                          help="warn-only for assignment-class lint")
    p_verify.add_argument("--grace-scan", action="store_true",
                          help="list assignment-class facts lacking value assertions")
    p_verify.set_defaults(func=cmd_verify)

    p_record = sub.add_parser("record", help="M4 RECORD (ledger idempotent append)")
    p_record.add_argument("workspace", nargs="?", default=".")
    p_record.add_argument("--event", default=None, help='event JSON: {"source_module":..., "event_type":..., "payload": {...}}')
    p_record.add_argument("--claim-migrate", nargs=3, metavar=("CLAIM_ID", "NEW_STATUS", "ACTOR"),
                          help="claim status migration (legality-checked)")
    p_record.add_argument("--read", nargs="?", const="", default=None, metavar="EVENT_TYPE",
                          help="read back events (event_type optional, all if omitted)")
    p_record.set_defaults(func=cmd_record)

    p_health = sub.add_parser("health", help="convergence health (M5)")
    p_health.add_argument("workspace", nargs="?", default=".")
    p_health.set_defaults(func=cmd_health)

    p_resume = sub.add_parser("resume",
                              help="crash/reboot recovery brief (#466, read-only)")
    p_resume.add_argument("workspace", nargs="?", default=".")
    p_resume.add_argument("--json", action="store_true")
    p_resume.set_defaults(func=cmd_resume)

    p_up = sub.add_parser("upgrade",
                          help="workspace framework-scaffold migration (#726)")
    p_up.add_argument("workspace", nargs="?", default=".")
    p_up.add_argument("--dry-run", action="store_true",
                      help="print the migration plan, write nothing")
    p_up.set_defaults(func=cmd_upgrade)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
