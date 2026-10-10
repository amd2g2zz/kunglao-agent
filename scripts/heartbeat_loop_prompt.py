#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""heartbeat_loop_prompt.py — the /loop heartbeat prompt (event-wakeup
topology restructure, issue 434).

The pre-434 body was a cron-injected OPERATING MANUAL: the same decision
table, ping ritual and note ritual re-injected every 5 minutes. The
restructured prompt splits along the topology:

  (a) CONSTITUTION — constitution() below: the static decision semantics
      (DISPATCH/BLOCKED/DEFERRED/PARK/SATURATED/CONVERGED imperatives +
      the action_taken contract), injected ONCE per session by the
      SessionStart hook — never by the cron;
  (b) STRATEGY SECTIONS — per decision, through the versioned seam
      (scripts/strategy_sections.py reads runs/round-strategy.json; the
      producer lands later, the seam renders nothing until it does);
  (c) GUARD GUIDANCE — dynamic, on Stop-hook fires (the WORKGUARD).

The cron body itself (build_prompt) is the WATCHDOG face: the heartbeat
demotes to a true watchdog and fires guidance ONLY when an expected event
did not arrive (report.watchdog.fired — scripts/loop_watchdog.py). A
quiet watchdog decision makes the wake a NO-OP: the LLM ends the turn
without re-reading any manual. The born-registered contract (#461) and
the scheduler's entry markers survive verbatim.

Usage:
    python scripts/heartbeat_loop_prompt.py <workspace> [--interval 5m]
    python scripts/heartbeat_loop_prompt.py <workspace> --verify

--verify (#461, HARD): the caller-side cron-registration acceptance check.
Reads the loop marker in <ws>/runs/.heartbeat.json (loop_registered);
missing file / absent / false marker -> exit 1 + stderr guidance (how to
register, what still failing means) — NEVER a silent RC 0. Run it right
after attempting CronCreate / /loop, and before the first dispatch.

Pure stdlib. Exit 0.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _difficulty_guidance(ws: str) -> str:
    """the difficulty-aware red-team rigor line ("" below hard).

    Guidance-only surface: the difficulty_thresholds policy decides whether
    the tier carries associated_task_consistency; a below-hard tier (and any
    resolution failure) keeps the prompt unchanged — guidance must never
    complexify simple samples."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from difficulty_thresholds import guidance_line
        line = guidance_line(ws)
    except Exception:  # guidance must never break the prompt build
        return ""
    return f"\n   → {line}" if line else ""


def constitution(ws: str) -> str:
    """(a) The once-per-session CONSTITUTION — the static decision
    semantics carried out of the cron body. Injected by the SessionStart
    hook; deterministic for a given workspace so sessions are comparable.
    """
    skill_dir = Path(__file__).resolve().parent.parent  # kunglao-agent/
    cc = str(skill_dir / "scripts" / "convergence_check.py")
    go = str(skill_dir / "scripts" / "goal_operationalization.py")
    orr = str(skill_dir / "scripts" / "oracle_runner.py")
    diff_line = _difficulty_guidance(ws)
    return f"""[kunglao-agent CONSTITUTION — injected once per session; the cron heartbeat no longer repeats it]
Decision semantics (run `python {cc} {ws} --json`, read `decision`, then act — every decision MUST produce a convergence-advancing action; no action = idle fault):
   DISPATCH   -> dispatch priority_ratio.py top action, no idling
   DISPATCH_VERIFIER -> dispatch the verifier the decision names
   BLOCKED    -> self-recover (resolve / stale_blocker_prune) or reactivate the failed claim
                 worker death: any runs/.worker-death-*.json surfaced by the decision/stuck report ->
                 dispatch a RESUME claim per record: read its artifacts list FIRST, verify + absorb
                 the existing products, continue from where the worker died — do NOT redo from zero
                 verification-undeclared BLOCKED (zero open claims, action names empty
                 goal-operationalization.yaml fields) -> complete the PRE-DISPATCH CONTRACT; there
                 is no claim to self-recover while the delivery contract is unaudited
   DEFERRED   -> check whether reactivation is possible (e.g. VM reachable again -> restore the claim)
   PARK       -> legal idle on external gates: record the wake_condition, then stop the heartbeat
                 (revive via mission_stall.py when the wake condition is met); a tick rc=2 with
                 idle_circuit_breaker is a MANDATORY stop — do not re-tick through it
   SATURATED  -> poll all active workers (no idle waiting)
   CONVERGED  -> run the closing checklist (blind_gate sign-off spot-check + kunglao-verify.py L1
                 re-run) + handoff-check PASS first, then stop the heartbeat (no cleanup before
                 convergence — deletion breaks dispatch)
PRE-DISPATCH CONTRACT (do once, before the first dispatch — while it is unaudited EVERY decide is
BLOCKED and CONVERGED is unreachable, no matter how good the deliverable is):
   1. goal-operationalization.yaml passes `python {go} <ws>/goal-operationalization.yaml`
      (draft: true = unaudited: fill deliverables/acceptance/not_done/diff_vs_verbatim/
      probe_cases, validate, then --stamp-dispatch — it is append-only after the stamp).
   2. The declared probe cases are ARMED (oracle/ case files + oracle/client.py) and green:
      `python {orr} <ws> --json` — with generalization required|unknown, zero armed cases
      keeps CONVERGED closed even after the operationalization passes.
WRITE CONTRACTS (the guards refuse and the FIRST refusal burns wall — know them up front):
   facts/F<NNN>.md MUST carry frontmatter id: F<NNN> + type: fact + title + status;
   claim-register.yaml ONLY via scripts/ws_yaml.py set|del — direct Bash/Edits are refused (#516).
Per-tick output contract: fill runs/.heartbeat-tick.json action_taken every tick with what the
tick advanced (dispatched/verified/solved/reactivated); an empty field = idle fault.
Worker pings use SendMessage "[ping HH:MM] step? stuck? eta?" and append replies to
runs/.ping-log.jsonl (isolation boundary: no agent teams; the orchestrator->worker ping is the
sanctioned channel).{diff_line}"""


def build_prompt(ws: str, interval: str = "5m") -> str:
    """The WATCHDOG cron body (issue 434): registration + one-command tick
    + the missed-event decision. The operating manual is NOT here — it is
    constitution(), injected once at SessionStart."""
    skill_dir = Path(__file__).resolve().parent.parent  # kunglao-agent/
    h = str(skill_dir / "scripts" / "hook_activation.py")
    tk = str(skill_dir / "scripts" / "heartbeat_tick.py")
    cc = str(skill_dir / "scripts" / "convergence_check.py")
    return f"""/loop {interval} kunglao-agent heartbeat (self-registration + watchdog, event-wakeup topology):

[Startup action — run once on the loop's first trigger]
python {h} {ws} --heartbeat-on --loop-registered   # register runs/.heartbeat.json AND mark loop_registered=true (#461) — this prompt body executing is the proof CronCreate accepted it

[Watchdog tick — the heartbeat fires ONLY on missed events]
0. python {tk} {ws}              # one-command tick: selfcheck + reconcile + renew + heartbeat-check + oracle-check + watchdog decision
                                 # NOTE (#415): a durable cron registered MID-SESSION only fires after the NEXT Claude Code session start —
                                 # a quiet gap right after registration is deploy-day shape, not a dead cron (--reset-continuity re-arms).
   - report.watchdog.fired == false -> this wake is a NO-OP: end the turn NOW. Events already wake the session
     (dispatch returns in-turn, worker completions between-turns, the Stop WORKGUARD judges turn-exit);
     re-reading manuals or dispatching from a quiet wake is the noise this watchdog replaced.
   - report.watchdog.fired == true  -> act ONLY on report.watchdog.reasons (missed events):
       heartbeat-gap   -> the cadence died: re-verify with python {h} {ws} --heartbeat-check, re-arm the chain if stale
       stuck-worker    -> smart-ping each named worker (SendMessage "[ping HH:MM] step? stuck? eta?", replies to runs/.ping-log.jsonl)
       step-failure    -> repair the failed mechanical step (the report's per-step stderr tails carry the text)
     then run python {cc} {ws} --json and follow the session constitution's decision semantics.
   - oracle_registered=false in the report -> run the Phase 0 task-oracle.yaml backfill now
   - tick exit=2 with idle_circuit_breaker -> MANDATORY stop — do not re-tick through it"""


def verify_loop(ws: str) -> int:
    """#461 HARD: prove the cron loop is registered — non-zero + stderr
    guidance when it is not (never silent).

    The loop marker (loop_registered) flips true only when the /loop prompt
    body itself executes (its first action passes --loop-registered) — a
    heartbeat FILE written by init / --heartbeat-on proves nothing about
    the cron. This is the caller-side acceptance check after attempting
    CronCreate / /loop.
    """
    hb = Path(ws) / "runs" / ".heartbeat.json"
    if not hb.exists():
        print("HEARTBEAT UNREGISTERED (HARD): no "
              f"{hb} — monitoring was never started. Fix: run "
              "hook_activation.py <ws> --heartbeat-on, then register the "
              "cron below.", file=sys.stderr)
        return 1
    try:
        data = json.loads(hb.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"HEARTBEAT UNREADABLE (HARD): {hb}: {exc} — "
              "re-register with --heartbeat-on.", file=sys.stderr)
        return 1
    if not data.get("loop_registered"):
        print(
            "CRON NOT REGISTERED (HARD): runs/.heartbeat.json exists "
            "but loop_registered is not true — the /loop heartbeat cron was "
            "never created (or never fired). Monitoring is NOT running and "
            "proceeding silently is forbidden. Fix NOW: re-run "
            "heartbeat_loop_prompt.py <ws> and pass its output to "
            "CronCreate */5 * * * * (or /loop 5m <prompt>); the loop's "
            "first action marks loop_registered=true. Re-run this --verify "
            "after TWO consecutive ticks (<= 2x interval); still "
            "failing then means the CronCreate itself failed — re-create it.",
            file=sys.stderr)
        return 1
    # #609 + #754 E2: the marker is a self-written claim — cross-check liveness.
    # A cron deleted after one successful fire must not keep verify vouching OK,
    # and (the live-run sample blind spot) a LONE registration tick must neither. Same
    # continuous-tick standard as the dispatch gate / --heartbeat-check: >=2
    # ticks with cadence <= 2x interval_min, newest <= STALE_MINUTES. Corrupt /
    # absent history counts as not ticking (fail-closed).
    from heartbeat import evaluate_tick_continuity  # noqa: E402 (shared source)
    alive, detail = evaluate_tick_continuity(
        data, log_path=Path(ws) / "runs" / ".heartbeat.log")
    if not alive:
        print(
            f"LOOP NOT TICKING (HARD): loop_registered=true but {detail} — "
            "the cron is registered yet not firing continuously (deleted after "
            "first fire, session ended, or never created). The marker is "
            "history, not liveness. Fix: re-register the /loop cron DURABLE "
            "(heartbeat_loop_prompt.py <ws> -> <ws>/.claude/"
            "scheduled_tasks.json via loop_scheduler upsert or re-run init), "
            "then re-run this --verify after TWO consecutive ticks.",
            file=sys.stderr)
        return 1
    print(f"OK: cron loop registered AND ticking continuously "
          f"(loop_registered=true, started {data.get('started_ts')}; {detail})")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: {Path(sys.argv[0]).name} <workspace> [--interval 5m] [--verify]", file=sys.stderr)
        return 2
    ws = sys.argv[1]
    # 0.1.6 version-consistency gate: LOOP BIRTH on a workspace whose
    # format stamp != the executing skill version refuses (rc 9) with
    # upgrade guidance — the transactional upgrade is the only path
    # forward for a mismatched workspace. `--verify` is exempt: it is the
    # read-only diagnostics face and must keep reporting on any workspace.
    if "--verify" not in sys.argv[2:] and Path(ws).is_dir():
        import template_version
        mismatch = template_version.version_mismatch(Path(ws))
        if mismatch is not None:
            print(f"REFUSE: {mismatch}. Run: python scripts/kunglao_upgrade.py "
                  f"{ws} — the transactional upgrade is the only path "
                  f"forward, then re-run the loop birth.",
                  file=sys.stderr)
            return 9
    if "--verify" in sys.argv[2:]:
        return verify_loop(ws)
    interval = "5m"
    if "--interval" in sys.argv:
        i = sys.argv.index("--interval")
        if i + 1 < len(sys.argv):
            interval = sys.argv[i + 1]
    print(build_prompt(ws, interval))
    return 0


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())
