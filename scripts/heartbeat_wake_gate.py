#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""heartbeat_wake_gate.py — the OS-scheduler wrapper the wake gate was missing (#1086 S18).

The pre-LLM gate exists and is tested (``heartbeat_tick.py <ws> --origin cron
--wake-gate``, #801 Face 1): a quiet verdict exits 0 and must inject NOTHING,
a wake verdict exits 3 and "the wrapper injects the loop prompt"
(scripts/mechanisms.yaml, wake_gate). The wrapper was the missing half — the
operator contract registered the PROMPT as the cron body (SKILL.md ->
heartbeat_loop_prompt.py stdout -> CronCreate */5), so a model turn happened
every five minutes whether or not there was work, and the verdict only ever
ran inside a turn whose tokens it existed to save.

This module is the thing the OS scheduler runs:

    cron -> heartbeat_wake_gate.py <ws> --wake-gate        [zero LLM]
              |- heartbeat_tick.py <ws> --origin cron --wake-gate --zero-llm
              |- rc 0 QUIET -> inject nothing, end   (quiet = zero model turns)
              |- rc 3 WAKE  -> draw the wake action (intelligent_scheduling:
              |                ONE recorded scheduling decision with its
              |                exact propensity), then inject the loop
              |                prompt EXACTLY ONCE — unless the draw is
              |                `none`, the legal zero-cost no-wake
              |                (recorded, nothing injected)
              |- rc 2 STOP  -> the #634 idle circuit breaker: MANDATORY stop,
              |                never inject, propagate rc 2
              `- fault      -> LOUD: stderr banner + rc 1, and fail toward
                              waking (the broken gate itself is a reason to
                              look). A fault is NEVER reported as QUIET —
                              silence here means the system never wakes,
                              which is worse than waking once too often.

Two layers with different jobs, never blended (#1086 S21): the GATE
answers "is there work to look at" (rc 0/3/2), the decision seat answers
"is a wake owed for it". The seat runs ONLY on a true WAKE verdict — a
QUIET verdict never draws again (pure overhead after the gate already
judged no wake), a STOP is the breaker's mandate (not a scheduling
action), and a gate FAULT injects unconditionally: a seat that could
veto a fault-wake would recreate the never-wakes failure this wrapper
exists to refuse. A broken seat fails toward waking the same way (loud,
inject anyway).

Delivery reuses the faces that already own it: the prompt body comes from the
emitter (heartbeat_loop_prompt.build_prompt — never a re-embedded copy, #598)
and the out-of-session turn is the external kicker's D4 shape
(build_kick_command + a detached ``claude -p`` fed the prompt on stdin). When
a session is still alive (external_kicker.session_is_dead says so) the
wrapper does NOT start a second orchestrator on the same workspace — the
staged prompt is the alive-session delivery and the live session's own
watchdog turn carries it.

Registration is a one-time manual step and commands are BUILT AS STRINGS
only (the kicker's D5 precedent — nothing here installs a cron):

    python scripts/heartbeat_wake_gate.py <ws> --print-registration

Usage:
    python scripts/heartbeat_wake_gate.py <ws> --wake-gate [--interval-min 5]
        [--claude-bin claude] [--dry-run] [--gate-timeout 240]
        [--decision-seed N]

Exit codes (the wrapper propagates the gate's verdict rc):
    0  QUIET — nothing injected (zero LLM, zero prompt bytes)
    3  WAKE  — the gate voted wake; the loop prompt was injected exactly
               once, or the scheduling action drew `none` and nothing was
               injected (the recorded zero-cost veto — see the receipt's
               decision block)
    2  STOP  — the tick's idle circuit breaker tripped (#634, mandatory)
    1  FAULT — gate crash / unexpected rc / verdict marker mismatch /
               delivery failure; loud on stderr, never a silent QUIET

Pure stdlib. Cross-platform: the registration face emits both a POSIX
crontab line and a Windows schtasks command.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# canonical warn: ONE implementation (process-wide dedupe + ledger face)
from kunglao_log import warn  # noqa: E402

SCRIPTS_DIR = Path(__file__).resolve().parent
TICK_SCRIPT = SCRIPTS_DIR / "heartbeat_tick.py"

#: the gate argv beyond the workspace: cron provenance (#616) + gate mode
#: + the zero-LLM host marker (#1086 S20) — THIS invocation has no model
#: turn in the loop, so the tick caps its machinery pass at cheap and
#: exempts the parked gate (the cheap clocks keep running through a quiet
#: day). The in-session tick the loop prompt teaches carries --wake-gate
#: WITHOUT this marker: its pass keeps the full cost-queued machinery.
GATE_ARGS = ("--origin", "cron", "--wake-gate", "--zero-llm")

#: the gate's verdict rc contract (heartbeat_tick.py --wake-gate)
GATE_RC_QUIET = 0
GATE_RC_WAKE = 3
GATE_RC_STOP = 2
#: the wrapper's own fault rc — never 0: a fault must not read as QUIET
RC_FAULT = 1

#: verdict markers the gate prints (the wrapper cross-checks rc AND marker —
#: an rc-0 pass without the QUIET marker is not in gate mode and must not be
#: trusted as quiet)
QUIET_MARKER = "QUIET:"
WAKE_MARKER = "WAKE:"

#: the staged prompt + the pass receipt (the kicker's staged-prompt/record
#: naming family; runs/.wake-gate.json stays the tick's quiet-streak state)
PROMPT_FILE_REL = Path("runs") / ".wake-gate-prompt.txt"
RECEIPT_REL = Path("runs") / ".wake-gate-receipt.json"

DEFAULT_INTERVAL_MIN = 5
DEFAULT_GATE_TIMEOUT_S = 240

_LOUD_PREFIX = "WAKE-GATE"


def _ts(now: datetime | None = None) -> str:
    dt = now or datetime.now(timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


def _loud(ws, message: str) -> None:
    """The fault face: a stderr banner + the canonical ledger trace. A fault
    that only changed the exit code would be silent to anyone not watching
    cron mail; the ledger row keeps it visible in the workspace."""
    print(f"{_LOUD_PREFIX} FAULT ({ws}): {message}", file=sys.stderr)
    warn("wake_gate_wrapper", message)


def _validate_interval(interval_min: int) -> None:
    """The kicker's D6 bound (value single-sourced in liveness_policy): a
    cadence at or beyond the 30-min activation TTL silently closes gates
    between passes."""
    from liveness_policy import ACTIVATION_TTL_MINUTES
    if interval_min <= 0:
        raise ValueError(f"interval must be positive, got {interval_min}")
    if interval_min >= ACTIVATION_TTL_MINUTES:
        raise ValueError(
            f"interval {interval_min}min >= activation TTL "
            f"{ACTIVATION_TTL_MINUTES}min — silent gate window between TTL "
            f"expiry and the next pass; use < {ACTIVATION_TTL_MINUTES}")


# ---------------------------------------------------------------------------
# registration (D5: strings only — nothing here installs a cron)
# ---------------------------------------------------------------------------

def gate_argv(ws, *, python_exe: str | None = None,
              tick: str | None = None) -> list[str]:
    """The command that runs the GATE: heartbeat_tick in --wake-gate mode
    with cron provenance and the zero-LLM host marker (#1086 S20 — the
    cheap-machinery ceiling this invocation owns). Single source for
    execution and documentation."""
    python = python_exe or sys.executable
    tick_path = Path(tick) if tick is not None else TICK_SCRIPT
    return [python, str(tick_path), str(ws), *GATE_ARGS]


def build_crontab_line(ws, *, interval_min: int = DEFAULT_INTERVAL_MIN,
                       python_exe: str | None = None,
                       script: str | None = None) -> str:
    """The POSIX crontab registration line. Runs the WRAPPER in gate mode —
    never the loop-prompt emitter (registering the prompt is the bypass
    #1086 closes)."""
    _validate_interval(interval_min)
    python = python_exe or sys.executable
    script_path = Path(script) if script is not None else Path(__file__)
    return (f"*/{interval_min} * * * * {python} {script_path} {ws} "
            f"--wake-gate")


def build_schtasks_command(task_name: str = "kunglao_wake_gate", *,
                           interval_min: int = DEFAULT_INTERVAL_MIN,
                           python_exe: str | None = None,
                           script: str | None = None,
                           ws=None) -> list[str]:
    """The Windows schtasks registration args (the kicker's D5 shape)."""
    _validate_interval(interval_min)
    python = python_exe or sys.executable
    script_path = Path(script) if script is not None else Path(__file__)
    return ["schtasks", "/create", "/tn", task_name, "/sc", "minute", "/mo",
            str(interval_min),
            "/tr", f'"{python}" "{script_path}" "{ws}" --wake-gate', "/f"]


def print_registration(ws, *, interval_min: int = DEFAULT_INTERVAL_MIN,
                       python_exe: str | None = None) -> None:
    print("[wake-gate registration — one-time manual step; strings only, "
          "nothing is installed here]")
    cron = build_crontab_line(ws, interval_min=interval_min,
                              python_exe=python_exe)
    sch = " ".join(build_schtasks_command(interval_min=interval_min,
                                          python_exe=python_exe, ws=ws))
    print(f"crontab : {cron}")
    print(f"schtasks: {sch}")
    print("QUIET (exit 0) injects nothing; WAKE (exit 3) injects the /loop "
          "prompt once; keep the durable /loop cron as the armed watchdog "
          "(#685 D5) — this line is the scheduler, not a replacement for it.")


# ---------------------------------------------------------------------------
# the gate pass
# ---------------------------------------------------------------------------

def _default_runner(cmd, *, timeout: int):
    """The real gate runner (the seam's contract: (cmd, timeout=...))."""
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def run_gate(ws, *, runner=None, python_exe: str | None = None,
             timeout_s: int = DEFAULT_GATE_TIMEOUT_S) -> dict:
    """Run one gate pass. Returns {"rc", "stdout", "stderr", "fault"} — a
    crashed/timed-out gate yields fault text and rc None; the CALLER decides
    loudly (never silently quiet). `runner` is the test seam."""
    cmd = gate_argv(ws, python_exe=python_exe)
    run = runner or _default_runner
    try:
        r = run(cmd, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return {"rc": None, "stdout": "", "stderr": "",
                "fault": f"gate timed out after {timeout_s}s"}
    except OSError as exc:
        return {"rc": None, "stdout": "", "stderr": "",
                "fault": f"gate could not run: {type(exc).__name__}: {exc}"}
    return {"rc": r.returncode, "stdout": r.stdout or "",
            "stderr": r.stderr or "", "fault": None}


def classify(gate: dict) -> dict:
    """Map one gate result to the outcome. rc AND marker must agree: an rc-0
    pass without the QUIET marker is not in gate mode, and trusting it as
    quiet is exactly the never-wakes failure this wrapper must refuse."""
    fault = gate.get("fault")
    if fault:
        return {"outcome": "fault", "reasons": [str(fault)]}
    rc = gate.get("rc")
    out = (gate.get("stdout") or "")
    if rc == GATE_RC_QUIET:
        if QUIET_MARKER in out:
            return {"outcome": "quiet", "reasons": []}
        return {"outcome": "fault",
                "reasons": [f"gate rc 0 without the {QUIET_MARKER} marker — "
                            "not in --wake-gate mode"]}
    if rc == GATE_RC_WAKE:
        if WAKE_MARKER in out:
            return {"outcome": "wake",
                    "reasons": [ln.strip() for ln in out.splitlines()
                                if ln.startswith(WAKE_MARKER)]}
        return {"outcome": "fault",
                "reasons": [f"gate rc 3 without the {WAKE_MARKER} marker"]}
    if rc == GATE_RC_STOP:
        return {"outcome": "stop", "reasons": ["idle circuit breaker (#634)"]}
    return {"outcome": "fault",
            "reasons": [f"unexpected gate rc {rc!r}"]}


# ---------------------------------------------------------------------------
# the injection (reuse: the emitter for the body, the kicker for the turn)
# ---------------------------------------------------------------------------

def loop_prompt(ws, *, interval_min: int = DEFAULT_INTERVAL_MIN) -> str:
    """The payload: the emitter's own body, never a re-embedded copy (#598)."""
    from heartbeat_loop_prompt import build_prompt
    return build_prompt(str(ws), f"{interval_min}m")


def session_alive(ws, *, now: datetime | None = None) -> bool:
    """The #39 dead-session predicate, single-sourced in external_kicker:
    a live session owns the wake and must never be duplicate-spawned."""
    import external_kicker as _kicker
    from liveness_policy import DEFAULT_STALE_MINUTES
    hb = None
    p = Path(ws) / "runs" / ".heartbeat.json"
    if p.exists():
        try:
            hb = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            hb = None  # corrupt -> recovery bias (the kicker's own posture)
    return not _kicker.session_is_dead(
        hb, now or datetime.now(timezone.utc), DEFAULT_STALE_MINUTES)


def _kick_session(prompt: str, ws, *, claude_bin: str = "claude") -> dict:
    """The out-of-session delivery — the kicker's D4 shape (build_kick_command
    + detached ``claude -p``, prompt via stdin), reusing its argv single
    source instead of a second command builder."""
    import external_kicker as _kicker
    cmd = _kicker.build_kick_command(claude_bin)
    flags = 0
    if os.name == "nt":
        flags = (subprocess.CREATE_NEW_PROCESS_GROUP
                 | subprocess.DETACHED_PROCESS)
    proc = subprocess.Popen(
        cmd, cwd=str(ws), stdin=subprocess.PIPE, creationflags=flags,
        start_new_session=os.name != "nt")
    proc.stdin.write(prompt.encode("utf-8"))
    proc.stdin.close()
    return {"delivered": "kicked", "pid": proc.pid, "command": cmd}


def inject(ws, *, reasons=(), prompt: str | None = None, deliver=None,
           claude_bin: str = "claude", dry_run: bool = False,
           interval_min: int = DEFAULT_INTERVAL_MIN,
           now: datetime | None = None) -> dict:
    """Deliver the loop prompt exactly once: stage it (the alive-session
    face), then kick a session only when nobody alive owns the wake. Raises
    on failure — the caller turns that into the loud fault rc."""
    ws = Path(ws)
    body = prompt if prompt is not None else loop_prompt(
        ws, interval_min=interval_min)
    stage = ws / PROMPT_FILE_REL
    stage.parent.mkdir(parents=True, exist_ok=True)
    stage.write_text(body, encoding="utf-8")
    if dry_run:
        return {"delivered": "dry-run", "prompt_file": str(stage)}
    if session_alive(ws, now=now):
        return {"delivered": "staged", "prompt_file": str(stage),
                "note": "live session owns the wake — no second orchestrator"}
    sender = deliver if deliver is not None else _kick_session
    record = sender(body, ws, claude_bin=claude_bin)
    if not isinstance(record, dict):
        record = {"delivered": "kicked", "result": record}
    record.setdefault("delivered", "kicked")
    record["prompt_file"] = str(stage)
    record["reasons"] = [str(r) for r in reasons]
    return record


# ---------------------------------------------------------------------------
# the wake decision seat (#1086 S21 — the seat's first runtime caller)
# ---------------------------------------------------------------------------

def _real_wake_decision(ws, *, rng=None, now=None):
    """One draw from the scheduling five via intelligent_scheduling.decide
    — the recorded action layer #685 built and nothing ever applied. The
    SEAT owns its own recording (runs/.scheduling-decision.json + one
    kind=scheduling signal row carrying the exact propensity and its
    probability_source); this face is only the call. Import stays lazy so
    the QUIET path never pays it."""
    import intelligent_scheduling
    return intelligent_scheduling.decide(ws, rng=rng, now=now)


def _write_receipt(ws, receipt: dict) -> None:
    try:
        p = Path(ws) / RECEIPT_REL
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(receipt, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(p)
    except OSError as exc:  # noqa: BLE001 — receipt is telemetry, not verdict
        print(f"{_LOUD_PREFIX}: receipt write failed: {exc}", file=sys.stderr)


def wake_pass(ws, *, runner=None, deliver=None,
              python_exe: str | None = None,
              claude_bin: str = "claude", dry_run: bool = False,
              interval_min: int = DEFAULT_INTERVAL_MIN,
              timeout_s: int = DEFAULT_GATE_TIMEOUT_S,
              now: datetime | None = None,
              decide=None, decision_rng=None) -> dict:
    """One wrapper pass: run the gate, then honor the verdict. Returns the
    receipt dict with "outcome", "rc", "injected", the delivery record,
    and — on a wake verdict — the "decision" block summarizing the seat's
    draw. ``decide`` is the seat seam (tests); ``decision_rng`` pins the
    draw for deterministic replay."""
    ws = Path(ws)
    gate = run_gate(ws, runner=runner, python_exe=python_exe,
                    timeout_s=timeout_s)
    verdict = classify(gate)
    outcome = verdict["outcome"]
    rc = {"quiet": GATE_RC_QUIET, "wake": GATE_RC_WAKE,
          "stop": GATE_RC_STOP, "fault": RC_FAULT}[outcome]
    receipt = {"ts": _ts(now), "outcome": outcome,
               "reasons": verdict["reasons"], "gate_rc": gate.get("rc"),
               "injected": False, "dry_run": dry_run}
    if outcome == "quiet":
        # the honest idle: zero output, zero bytes staged, no receipt —
        # and no decision draw either (the gate already judged no wake;
        # sampling the seat again here is pure overhead)
        return {**receipt, "rc": rc}
    if outcome == "stop":
        _loud(ws, "the tick's idle circuit breaker tripped (gate rc 2) — "
                  "MANDATORY stop, nothing injected (#634)")
        _write_receipt(ws, receipt)
        return {**receipt, "rc": rc}
    if outcome == "wake":
        # the two layers, in order: the gate said there is work to look
        # at; the seat says whether a wake is OWED for it. STOP and gate
        # FAULT never reach here — a mandated stop is not a scheduling
        # action, and a fault-wake must not be vetoable (never-wakes).
        seat = decide if decide is not None else _real_wake_decision
        try:
            decision = seat(ws, rng=decision_rng, now=now)
        except Exception as exc:  # noqa: BLE001 — loud, fail toward waking
            _loud(ws, f"the wake decision seat failed "
                      f"({type(exc).__name__}: {exc}) — injecting anyway")
            receipt["decision"] = {"fault": f"{type(exc).__name__}: {exc}"}
        else:
            receipt["decision"] = {
                "action": decision.get("action"),
                "propensity": decision.get("propensity"),
                "source": decision.get("source"),
                "k": decision.get("k"),
                "probability_source": decision.get("probability_source"),
            }
            if decision.get("action") == "none":
                # intelligent_scheduling.NULL_ACTION — the legal zero-cost
                # result: the gate said wake, the action layer said no
                # wake is owed. Not a fault: the decision is recorded,
                # nothing is injected, the gate's verdict rc stands.
                print(f"wake-gate: WAKE — the scheduling action drew none "
                      f"(p={decision.get('propensity')}); nothing injected")
                _write_receipt(ws, receipt)
                return {**receipt, "rc": rc}
    # wake with an acting draw, a broken seat, or fault failing toward
    # waking: the session gets the prompt
    try:
        delivery = inject(ws, reasons=verdict["reasons"], deliver=deliver,
                          claude_bin=claude_bin, dry_run=dry_run, now=now,
                          interval_min=interval_min)
        receipt["injected"] = True
        receipt["delivery"] = delivery
    except Exception as exc:  # noqa: BLE001 — loud, never a silent quiet
        _loud(ws, f"loop-prompt injection failed: {type(exc).__name__}: {exc}")
        receipt["outcome"] = "fault"
        receipt["reasons"] = [*verdict["reasons"],
                              f"injection failed: {exc}"]
        receipt["fault"] = f"injection failed: {exc}"
        _write_receipt(ws, receipt)
        return {**receipt, "rc": RC_FAULT}
    if outcome == "fault":
        _loud(ws, "gate fault — failing toward waking so a broken gate "
                  f"cannot sleep the system forever: {'; '.join(verdict['reasons'])}")
    else:
        action = (receipt.get("decision") or {}).get("action")
        print(f"wake-gate: WAKE — scheduling action {action}, injected the "
              f"loop prompt (delivered={delivery.get('delivered')}, "
              f"prompt={delivery.get('prompt_file')})")
    _write_receipt(ws, receipt)
    return {**receipt, "rc": rc}


def main(argv: list[str] | None = None) -> int:
    from _boot import reconfigure_stdout
    reconfigure_stdout()
    args = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(
        prog="heartbeat_wake_gate.py",
        description="The OS-scheduler wrapper of the pre-LLM wake gate "
                    "(#1086 S18): run heartbeat_tick --wake-gate, inject the "
                    "loop prompt ONLY on a wake verdict.")
    parser.add_argument("workspace", help="initialized kunglao workspace")
    parser.add_argument("--wake-gate", action="store_true",
                        help="gate mode — REQUIRED for a pass (the "
                             "registration line carries it so the crontab "
                             "entry names the gate; refusing without it "
                             "fails fast on a hand-trimmed registration)")
    parser.add_argument("--interval-min", type=int,
                        default=DEFAULT_INTERVAL_MIN,
                        help="the cron cadence in minutes (default 5; must "
                             "stay under the 30-min activation TTL)")
    parser.add_argument("--claude-bin", default="claude",
                        help="the claude CLI binary for the out-of-session "
                             "wake delivery")
    parser.add_argument("--dry-run", action="store_true",
                        help="decide + stage the prompt, never spawn a "
                             "session (tests and manual inspection)")
    parser.add_argument("--gate-timeout", type=int,
                        default=DEFAULT_GATE_TIMEOUT_S,
                        help="gate subprocess timeout in seconds")
    parser.add_argument("--decision-seed", type=int, default=None,
                        help="pin the wake decision's rng for deterministic "
                             "replay (tests and inspection — the emitted "
                             "registration lines never carry it; production "
                             "draws OS entropy)")
    parser.add_argument("--print-registration", action="store_true",
                        help="emit the crontab/schtasks registration lines "
                             "(strings only) and exit")
    parsed = parser.parse_args(args)
    if parsed.print_registration:
        print_registration(parsed.workspace,
                           interval_min=parsed.interval_min)
        return 0
    if not parsed.wake_gate:
        print("REFUSE: pass --wake-gate (copy the emitted registration line "
              "— heartbeat_wake_gate.py <ws> --print-registration); the gate "
              "verdict is the whole point of this wrapper",
              file=sys.stderr)
        return 2
    try:
        _validate_interval(parsed.interval_min)
    except ValueError as exc:
        print(f"REFUSE: {exc}", file=sys.stderr)
        return 2
    try:
        import kunglao_log
        kunglao_log.set_warn_workspace(Path(parsed.workspace))
    except Exception as exc:  # ledger pinning is best-effort; warn() is fail-open
        warn("wake_gate_wrapper", f"set_warn_workspace failed: {exc}")
    receipt = wake_pass(
        parsed.workspace, python_exe=None, claude_bin=parsed.claude_bin,
        dry_run=parsed.dry_run, interval_min=parsed.interval_min,
        timeout_s=parsed.gate_timeout,
        decision_rng=(random.Random(parsed.decision_seed)
                      if parsed.decision_seed is not None else None))
    return receipt["rc"]


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())
