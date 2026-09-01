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
import template_version

from _hooks_path import load_module_by_path  # #863 Family B: loader delegation (#671 authority)


# Exit codes used by the stale-workspace gate (#748).
#   5 = workspace template stamp is older than the active skill version, or
#       the stamp is missing entirely — refuse with an explicit "run
#       /kunglao-agent:upgrade <ws> first" rather than silently letting the
#       loop run against a stale workspace (the #717 三层闸门 escape pattern).
RC_STALE_WORKSPACE = 5

# #754 T3: analysis-entry heartbeat verify failure — monitoring is not
# verifiably alive (<2 consecutive ticks / cadence gap > 2x interval /
# last tick > STALE_MINUTES). Distinct from rc=5 so SKILL.md can map each
# refusal to its exact remediation.
RC_HEARTBEAT_VERIFY_FAIL = 6


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


def cmd_check_stale(args) -> int:
    """#748: stale-workspace gate — emit a JSON envelope and exit 5 when the
    workspace stamp is older than the active skill version (or missing
    entirely). Used by `/kunglao-agent:analysis` and `/kunglao-agent:resume`
    SKILL.md bodies as the first step of entry.

    JSON envelope:

        {
          "status":     "stale" | "current" | "no-stamp" | "deploy-drift",
          "rc":         0 | 5,
          "workspace_stamp": "0.1.0" | null,
          "skill_version":   "0.1.3",
          "advice":     "run /kunglao-agent:upgrade <workspace> first" | null
        }
    """
    ws = Path(args.workspace).resolve()
    skill_v = template_version.read_skill_version()
    ws_v = template_version.read_workspace_version(ws)
    if ws_v is None:
        envelope = {
            "status": "no-stamp",
            "rc": RC_STALE_WORKSPACE,
            "workspace_stamp": None,
            "skill_version": skill_v,
            "advice": f"run /kunglao-agent:init {ws} first",
        }
        print(json.dumps(envelope, ensure_ascii=False))
        return RC_STALE_WORKSPACE
    try:
        ws_key = template_version._semver_tuple(ws_v)
        skill_key = template_version._semver_tuple(skill_v)
    except Exception:
        envelope = {
            "status": "stale",
            "rc": RC_STALE_WORKSPACE,
            "workspace_stamp": ws_v,
            "skill_version": skill_v,
            "advice": f"workspace stamp {ws_v!r} not parseable — "
                      f"run /kunglao-agent:init {ws} first",
        }
        print(json.dumps(envelope, ensure_ascii=False))
        return RC_STALE_WORKSPACE
    if ws_key < skill_key:
        envelope = {
            "status": "stale",
            "rc": RC_STALE_WORKSPACE,
            "workspace_stamp": ws_v,
            "skill_version": skill_v,
            "advice": f"run /kunglao-agent:upgrade {ws} first "
                      f"(stamp {ws_v} < skill {skill_v})",
        }
        print(json.dumps(envelope, ensure_ascii=False))
        return RC_STALE_WORKSPACE
    # #783 T5 third criterion: deployed framework copies are present
    # (phase-2 semantics) — the manifest digest decides, not just the stamp.
    # Priority: no-stamp > stale(version) > deploy-drift > current (a
    # version upgrade overwrites the copies, so stale wins on purpose).
    if (ws / ".claude" / "hooks").is_dir():
        import deploy_manifest as deploy_manifest
        try:
            drift = deploy_manifest.deploy_drift(ws)
        except Exception as exc:  # noqa: BLE001 — fail loud-ish, stay a gate
            drift = {"drift": True, "reason": f"probe-error:{exc}",
                     "observed": None, "expected": None,
                     "carrier_digest": None}
        if drift.get("drift"):
            envelope = {
                "status": "deploy-drift",
                "rc": RC_STALE_WORKSPACE,
                "workspace_stamp": ws_v,
                "skill_version": skill_v,
                "drift_reason": drift.get("reason"),
                "deployed_digest": drift.get("carrier_digest"),
                "observed_digest": drift.get("observed"),
                "skill_manifest_digest": drift.get("expected"),
                "advice": f"run /kunglao-agent:upgrade {ws} first "
                          f"(framework copies drifted)",
            }
            print(json.dumps(envelope, ensure_ascii=False))
            return RC_STALE_WORKSPACE
    envelope = {
        "status": "current",
        "rc": 0,
        "workspace_stamp": ws_v,
        "skill_version": skill_v,
        "advice": None,
    }
    print(json.dumps(envelope, ensure_ascii=False))
    return 0


def cmd_resume(args) -> int:
    """#466: crash/reboot recovery brief — pure delegation to
    kunglao_resume.main (READ-ONLY: decide() direct, never cc.main()).

    #748: stale-workspace gate runs first; if the workspace template stamp
    trails the skill version, refuse with RC=5 and direct the operator to
    `/kunglao-agent:upgrade <workspace>` (user must explicitly act —
    no auto-fix per #748 user ruling 2026-08-26).
    """
    ws = Path(args.workspace).resolve()
    rc = _gate_stale_workspace(ws)
    if rc != 0:
        return rc
    import kunglao_resume as kresume
    argv = [str(ws)]
    if args.json:
        argv.append("--json")
    return kresume.main(argv)


def _gate_stale_workspace(ws: Path) -> int:
    """Shared #748 gate — emits the check-stale envelope to stderr and
    returns RC_STALE_WORKSPACE on a stale workspace, 0 otherwise. Used by
    cmd_resume; cmd_check_stale emits its own envelope and does not call
    this (it is the canonical consumer)."""
    import sys
    skill_v = template_version.read_skill_version()
    ws_v = template_version.read_workspace_version(ws)
    if ws_v is None:
        print(
            f"kunglao: workspace {ws} has no version stamp — "
            f"run /kunglao-agent:init {ws} first.",
            file=sys.stderr,
        )
        return RC_STALE_WORKSPACE
    try:
        ws_key = template_version._semver_tuple(ws_v)
        skill_key = template_version._semver_tuple(skill_v)
    except Exception:
        print(
            f"kunglao: workspace stamp {ws_v!r} is not parseable — "
            f"run /kunglao-agent:init {ws} first.",
            file=sys.stderr,
        )
        return RC_STALE_WORKSPACE
    if ws_key < skill_key:
        print(
            f"kunglao: workspace stamp {ws_v} trails skill version {skill_v} — "
            f"run /kunglao-agent:upgrade {ws} first.",
            file=sys.stderr,
        )
        return RC_STALE_WORKSPACE
    return 0


def _gate_heartbeat_rearm(ws: Path) -> int:
    """#754 T3: the analysis-entry machine self-check (does not rely on the
    orchestrator or the user remembering how heartbeats work):

      1. durable reconcile — upsert <ws>/.claude/scheduled_tasks.json with our
         idempotent loop entry (aging rebuild: a deleted/expired Claude Code
         durable schedule is re-created here BEFORE anyone enters the loop);
      2. continuous-tick verify — heartbeat_loop_prompt.verify_loop() with the
         SAME evaluate_tick_continuity standard as the dispatch gate / 
         --heartbeat-check (#754 E2): >=2 consecutive ticks, gaps <= 2x
         interval_min, newest <= 35min.

    Returns 0 when the entry is clear; RC_HEARTBEAT_VERIFY_FAIL (6) with an
    explicit stderr hint otherwise. The reconcile is best-effort loud: a
    scheduler-write failure warns but the VERIFY verdict stays authoritative.
    """
    try:
        import loop_scheduler as ls
        ls.upsert_durable_loop(ws)
    except Exception as exc:  # noqa: BLE001 — advisory loud, verify decides
        print(
            f"kunglao: durable /loop reconcile FAILED ({exc}) - register "
            f"manually: uv run --project <skill> <skill>/scripts/"
            f"loop_scheduler.py {ws}",
            file=sys.stderr)
    import heartbeat_loop_prompt as hlp
    if hlp.verify_loop(str(ws)) != 0:
        print("heartbeat verify failed — run /kunglao-agent:resume for "
              "re-arm guidance", file=sys.stderr)
        return RC_HEARTBEAT_VERIFY_FAIL
    print("OK: analysis entry clear - stale gate PASS, durable /loop "
          f"registered ({ws / '.claude' / 'scheduled_tasks.json'}), "
          "heartbeat ticking continuously")
    return 0


def cmd_analysis(args) -> int:
    """#754 T3: the /kunglao-agent:analysis ENTRY gate chain — run once
    before entering the convergence loop (SKILL.md contract):

      1. _gate_stale_workspace (#748, same mount-point pattern as resume);
      2. _gate_heartbeat_rearm (#754): durable-loop aging rebuild +
         continuous-tick verify; rc=6 maps to the re-arm hint.

    Pure gate/checker surface: entering the loop remains the orchestrator's
    job (this command decides READINESS mechanically, then exits).
    """
    ws = Path(args.workspace).resolve()
    rc = _gate_stale_workspace(ws)
    if rc != 0:
        return rc
    return _gate_heartbeat_rearm(ws)


def cmd_upgrade(args) -> int:
    """#726: workspace framework-scaffold migration — pure delegation to
    kunglao_upgrade.main. Hyphenated filename blocks a plain import; the
    module is loaded via importlib (same pattern the test suite uses for
    kunglao-init). #863 Family B: by-path prologue collapsed into the
    canonical loader (via scripts/_hooks_path)."""
    mod_path = Path(__file__).resolve().parent / "kunglao_upgrade.py"
    mod = load_module_by_path("kunglao_upgrade", mod_path)
    argv = [str(args.workspace)]
    if args.dry_run:
        argv.append("--dry-run")
    return mod.main(argv)


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="kunglao.py",
        description="kunglao-agent unified entry",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "refusal exit codes:\n"
            "  5 = stale workspace (template stamp trails or predates the skill "
            "version) — run /kunglao-agent:upgrade <ws> first\n"
            "  6 = heartbeat verify failed (analysis entry) — run "
            "/kunglao-agent:resume for re-arm guidance\n"
            "(resume/check-stale return 5; analysis entry returns 5 or 6)"
        ),
    )
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
                              help="crash/reboot recovery brief (read-only)")
    p_resume.add_argument("workspace", nargs="?", default=".")
    p_resume.add_argument("--json", action="store_true")
    p_resume.set_defaults(func=cmd_resume)

    p_check_stale = sub.add_parser(
        "check-stale",
        help="stale-workspace gate: JSON envelope + rc 0/5 "
             "(status=current|stale|no-stamp); use this before "
             "/kunglao-agent:analysis or /kunglao-agent:resume on a "
             "workspace whose template stamp may trail the skill")
    p_check_stale.add_argument("workspace", nargs="?", default=".")
    p_check_stale.set_defaults(func=cmd_check_stale)

    p_up = sub.add_parser("upgrade",
                          help="workspace framework-scaffold migration")
    p_up.add_argument("workspace", nargs="?", default=".")
    p_up.add_argument("--dry-run", action="store_true",
                      help="print the migration plan, write nothing")
    p_up.set_defaults(func=cmd_upgrade)

    p_analysis = sub.add_parser(
        "analysis",
        help="analysis entry gate: stale gate -> durable /loop "
             "reconcile -> continuous-tick verify; rc0=clear, 5=stale, "
             "6=heartbeat verify failed")
    p_analysis.add_argument("workspace", nargs="?", default=".")
    p_analysis.set_defaults(func=cmd_analysis)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
