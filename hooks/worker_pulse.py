#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""worker_pulse.py - convergence pulse injected after every worker completion (v1.9.8).

WHY: v1.9's convergence loop is agent-invoked — the orchestrator must
REMEMBER to run convergence_check.py every turn. When it forgets (or gets
absorbed in processing a worker report), there is no backstop: the loop
drifts, and "kunglao-agent got dumb" (user's words, 原文 Chinese: kunglao-agent 笨了) shows up again as a mystery. This hook makes
the convergence state arrive automatically: at the exact moment a worker
completes (PostToolUse on Agent), the orchestrator receives a compact
"where are we, what's next" pulse — zero effort, zero forgetting.

SMART = narrow + alive-only (same philosophy as dispatch_gate):
  - fires ONLY when a worker/agent call completed AND the payload carries a
    claim dispatch prefix `[T<N> tools=...] claim <C-NN>` — i.e. a kunglao-agent
    worker just finished. Everything else → silent.
  - fires ONLY while kunglao-agent is ACTIVATED (30-min TTL, renewed by the
    orchestrator at Phase 0 / heartbeat). No activation / expired = hooks
    sleep. A stray session can't receive pulses it didn't sign up for.
  - INJECTES guidance (additionalContext), never aborts. The orchestrator
    still owns the decision; the pulse is a heuristic nudge, not a gate.

Output shape (one compact block, #55: wrapped in <worker-signal> when it
enters the agent's additionalContext — stderr stays untagged):
  [worker_pulse] W-<n> finished
  DECISION: <DISPATCH|SATURATED|BLOCKED|DISPATCH_VERIFIER|CONVERGED> — <action>
  next up: <top dispatchable claim via priority_ratio.py — the sanctioned scorer (#499)>
  flags: stuck=<...> failure-blocked=<...> partial=<...>
  TASKSTOP: W-<n> delivered — TaskStop now          # #88: on a final-state worker

Pure read: reads claim-register.yaml + runs convergence_check/priority_ratio
in subprocess. No state writes, no files touched (except the ledger side-effect
of convergence_check, which is by-design).

TASKSTOP delivery reminder (#88, D1): when the just-completed dispatch's
worker status file shows a FINAL state (done / blocked), the pulse appends
`TASKSTOP: W-<n> delivered — TaskStop now` — the delivery moment is exactly
when the orchestrator is most likely to forget the stop. A delivered-but-
unstopped worker holds a slot forever (the zombie root cause). In-progress
workers get no reminder (silent by default).

Wiring (in .claude/settings.json PostToolUse, Agent matcher — alongside
worker_budget):
  {"matcher": "Agent", "hooks": [{"type": "command",
    "command": "uv run --project <skill_root> <skill_root>/hooks/worker_pulse.py"}]}
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from _path_hygiene import load_hooks_lib, scripts_on_path  # #671 authority

SKILL_DIR = Path(__file__).resolve().parent.parent  # kunglao-agent/

# v1.9.29 (#38): soft stale-worker detection for the non-dispatch PostToolUse
# path. Worker-status parsing lives in lib_kunglao (THE single parse point,
# #444): parse_worker_status(_tokens) returns the LAST `status:` token wins
# result over both line shapes. Import is lazy (worker_budget precedent) and
# fail-open ('' on any error — the hard REJECT is worker_budget's job).
STUCK_MIN = 20  # minutes — mirrors backtrack_gate default --stuck-min 20

# #55 XML injection standard: every worker_pulse additionalContext payload is
# a worker lifecycle/status signal -> wrapped in <worker-signal>...</worker-signal>
# (references/xml-injection-standard.md). Tags MARK information — never gate:
# pulse content, rc and the JSON envelope are unchanged; STDERR (the operator
# channel, e.g. the rc=3 BLOCKED face) stays untagged.
WORKER_SIGNAL_TAG = "worker-signal"


def _worker_signal(text: str) -> str:
    """Wrap one pulse payload in the #55 producer tag."""
    return f"<{WORKER_SIGNAL_TAG}>\n{text}\n</{WORKER_SIGNAL_TAG}>"


def _worker_lib():
    """hooks/lib_kunglao — the worker-status protocol single parse point (#444).

    #770: by-path canonical loader — a bare import resolves by ambient
    sys.path order and re-binds to the scripts twin whenever any earlier
    module inserted scripts/ ahead of hooks/."""
    return load_hooks_lib()


def _check_stale_workers(ws: Path) -> str:
    """Soft mtime-stale detection for the non-dispatch PostToolUse path (#38).

    Scans `ws/runs/worker-status-*.md` for in-progress files whose mtime
    exceeds STUCK_MIN. Returns a human-readable message naming each stale
    worker + age, or '' if none. NEVER aborts — the hard REJECT is
    worker_budget's job (check_backtrack_gate). Any OSError / missing runs/
    dir / protocol import error -> '' (no crash, no false alarm)."""
    runs = ws / "runs"
    if not runs.is_dir():
        return ''
    try:
        parse_tokens = _worker_lib().parse_worker_status_tokens
    except Exception:
        return ''
    now = time.time()
    stale = []
    try:
        for p in runs.glob("worker-status-*.md"):
            try:
                tokens = parse_tokens(p.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            if not tokens:
                continue
            last = tokens[-1].replace("-", "_")
            if last != "in_progress":
                continue
            try:
                age_min = (now - p.stat().st_mtime) / 60
            except OSError:
                continue
            if age_min > STUCK_MIN:
                stale.append(f"{p.name} (age {age_min:.0f}m)")
    except OSError:
        return ''
    if not stale:
        return ''
    return (f"[worker_pulse] {len(stale)} stale in-progress worker(s) "
            f"(> {STUCK_MIN}m no status-file update): " + ", ".join(stale) +
            " - intervene or force a `## backtrack` block.")


def _resolve_workspace(payload: dict) -> Path | None:
    cwd = Path(payload.get("cwd") or payload.get("workspace") or ".")
    for base in [cwd / "malware-analysis-workspace", cwd]:
        if (base / "claim-register.yaml").exists():
            return base
    return None


def _kunglao_active(ws: Path) -> bool:
    """Strict activation: worker_pulse fires only if explicitly activated AND
    not expired (30-min TTL). Default-inactive — a non-kunglao-agent session gets
    zero injection. Mirrors dispatch_gate.py::_kunglao_active."""
    state_path = ws / ".hook_state.json"
    if not state_path.exists():
        return False
    try:
        with scripts_on_path():  # #671 scoped membership
            import hook_activation as ha
        return ha.is_active_strict(ws, "worker_pulse")
    except Exception:
        return False


def _was_dispatch(payload: dict) -> bool:
    """Did the completed Agent call look like a kunglao-agent worker dispatch?
    Matches the dispatch prefix in the prompt the orchestrator sent."""
    tool_input = payload.get("tool_input") or {}
    prompt_parts = []
    if isinstance(tool_input, dict):
        for k in ("prompt", "description", "task"):
            v = tool_input.get(k)
            if v:
                prompt_parts.append(str(v))
    else:
        prompt_parts = [str(tool_input)]
    lib = load_hooks_lib()
    return bool(lib.parse_dispatch(" ".join(prompt_parts))[2] is not None)


def _run_py(args: list, ws: Path):
    """Run a kunglao-agent script. Args are absolute paths (cwd is the workspace,
    so relative paths would resolve against it, not the skill dir — v1.9.8
    bug caught in the first pulse test)."""
    try:
        return subprocess.run(
            [sys.executable] + args,
            capture_output=True, text=True, timeout=20,
            cwd=str(ws), encoding="utf-8", errors="replace",
        )
    except (subprocess.SubprocessError, OSError):
        return None


def _delivery_reminder(ws: Path) -> str:
    """TASKSTOP delivery-moment reminder (#88 D1).

    When the just-completed dispatch's worker status file shows a FINAL state
    (`done` / `blocked` — LAST `status:` token wins, lib_kunglao protocol),
    remind the orchestrator to TaskStop the delivered worker: a
    delivered-but-unstopped background worker holds a slot forever. Returns
    '' when no delivered worker is found (in-progress or missing = silent)."""
    runs = ws / "runs"
    if not runs.is_dir():
        return ''
    try:
        lib = _worker_lib()
        parse_status = lib.parse_worker_status
        waiting_status = lib.WAITING_WORKER_STATUS
    except Exception:
        return ''
    delivered = []
    try:
        for p in runs.glob("worker-status-*.md"):
            try:
                last = parse_status(p.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            if last == waiting_status:
                # delivered-but-alive: the wait loop re-arms this worker on
                # the next dispatch — it is not a zombie, so the TaskStop
                # reminder must skip it
                continue
            if last is not None and last.replace("-", "_") in ("done", "blocked"):
                delivered.append(p.name.removeprefix("worker-status-").removesuffix(".md"))
    except OSError:
        return ''
    if not delivered:
        return ''
    return "TASKSTOP: " + ", ".join(delivered) + " delivered - TaskStop now"


def _build_pulse(ws: Path) -> tuple[str, str | None]:
    """Compact convergence snapshot: decision + next-up claim + flags.
    Returns (pulse, decision) — decision is None when convergence_check
    output is unavailable."""
    lines = ["[worker_pulse] worker completed - convergence pulse (auto):"]

    cc = _run_py([str(SKILL_DIR / "scripts" / "convergence_check.py"), str(ws), "--json"], ws)
    d = None
    if cc and cc.returncode in (0, 1, 2, 3, 4):
        try:
            d = json.loads(cc.stdout)
        except json.JSONDecodeError:
            d = None
    if d:
        lines.append(f"DECISION: {d['decision']} - {d['action']}")
        flags = []
        if d.get("stuck_workers"):
            flags.append(f"stuck={[w['worker'] for w in d['stuck_workers']]}")
        if d.get("failure_blocked"):
            flags.append(f"failure-blocked={list(d['failure_blocked'])}")
        if d.get("partial_count"):
            flags.append(f"partial={d['partial_count']}")
        if d.get("active_blockers"):
            flags.append(f"blockers={d['active_blockers']}")
        # W-15 (#444): done-without-files at the exact delivery-review moment —
        # the pulse is where "report done" gets double-checked (design D3).
        if d.get("done_artifact_violations"):
            flags.append(f"w15={[w['worker'] for w in d['done_artifact_violations']]}")
        # DLQ (#36): surface quarantined (DEAD) claim count. Fail-open — a
        # missing module or register must never break the convergence pulse.
        try:
            with scripts_on_path():  # #671 scoped membership
                import dead_letter as _dl  # sibling in scripts/
                _quarantined = _dl.count_dead(ws)
                if _quarantined:
                    flags.append(f"quarantined={_quarantined}")
        except Exception:
            pass
        if flags:
            lines.append("flags: " + "; ".join(flags))

    # next-up claim via priority_ratio.py — THE authoritative scorer (#499:
    # specs/phase-4/contract.md §1 lands DECIDE action ranking on
    # priority_ratio; the legacy weighted module is deprecated, #446 retires it).
    pr = _run_py([str(SKILL_DIR / "scripts" / "priority_ratio.py"), str(ws), "--json"], ws)
    if pr and pr.returncode == 0:
        try:
            actions = json.loads(pr.stdout)
        except json.JSONDecodeError:
            actions = None
        if isinstance(actions, list):
            # caller-side filtering is the caller's job (contract §1 — the pure
            # function takes no ws): drop failure-blocked claims (cc flags them)
            # and claims convergence_check no longer counts open (e.g. RETRACTED
            # — ratio.is_open keys off status_defs.TERMINAL, cc off
            # TERMINAL_WITH_RETRACTED; cc is the convergence truth face).
            failure_blocked = set(d.get("failure_blocked") or []) if d else set()
            cc_open = ({c.get("id") for c in d.get("open_claims", []) if c.get("id")}
                       if d else None)
            eligible = [a for a in actions
                        if a.get("claim_id") not in failure_blocked
                        and (cc_open is None or a.get("claim_id") in cc_open)]
            if eligible:
                top = eligible[0]
                lines.append(f"next up: {top['claim_id']} (score {top['score']}) {top.get('action', '')}")
            else:
                lines.append("next up: no dispatchable claims (check DECISION above)")

    if len(lines) == 1:
        return "", (d or {}).get("decision")
    lines.append("(decide per convergence-loop; the pulse is a heuristic, not a verdict)")
    return "\n".join(lines), (d or {}).get("decision")


def main(payload: dict | None = None) -> int:
    """Hook entry. `payload=None` reads stdin (the wired subprocess shape);
    an explicit payload dict is the in-process test seam."""
    if payload is None:
        try:
            payload = json.loads(sys.stdin.read() or "{}")
        except json.JSONDecodeError:
            return 0

    ws = _resolve_workspace(payload)
    if ws is None:
        return 0
    if not _kunglao_active(ws):
        return 0  # not activated or expired — hooks sleep
    if not _was_dispatch(payload):
        # v1.9.29 (#38): even on the non-dispatch path, surface mtime-stale
        # in-progress workers as a soft additionalContext. NEVER aborts
        # (rc=0); the hard REJECT is worker_budget.check_backtrack_gate.
        stale_msg = _check_stale_workers(ws)
        if stale_msg:
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": _worker_signal(stale_msg),
                }
            }, ensure_ascii=False))
        return 0  # not a kunglao-agent worker completion — soft pulse only

    pulse, decision = _build_pulse(ws)
    # #88 D1: delivery-moment TASKSTOP reminder — fires on a dispatch
    # completion whose worker status file shows a final state.
    reminder = _delivery_reminder(ws)
    if reminder and pulse:
        pulse = pulse + "\n" + reminder
    # v1.9.29 (R5): BLOCKED/SATURATED are mechanical — mark the worker
    # completion as failed with the pulse as context, so the orchestrator
    # cannot proceed past a blocked/saturated convergence state.
    if pulse and decision in ("BLOCKED", "SATURATED"):
        print(pulse, file=sys.stderr)
        return 3  # BLOCKED — see hook_exit_codes.py
    if not pulse:
        if reminder:
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": _worker_signal(
                        "[worker_pulse] " + reminder),
                }
            }, ensure_ascii=False))
        return 0
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": _worker_signal(pulse),
        }
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
