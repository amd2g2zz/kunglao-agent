#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""worker_pulse.py - convergence pulse injected after every worker completion (v1.9.8).

WHY: v1.9's convergence loop is agent-invoked — the orchestrator must
REMEMBER to run convergence_check.py every turn. When it forgets (or gets
absorbed in processing a worker report), there is no backstop: the loop
drifts, and "kunglao-agent 笨了" shows up again as a mystery. This hook makes
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

Output shape (one compact block):
  [worker_pulse] W-<n> finished
  DECISION: <DISPATCH|SATURATED|BLOCKED|DISPATCH_VERIFIER|CONVERGED> — <action>
  next up: <top dispatchable claim via priority.py>
  flags: stuck=<...> failure-blocked=<...> partial=<...>
  TASKSTOP: W-<n> delivered — TaskStop now          # #88: on a final-state worker

Pure read: reads claim-register.yaml + runs convergence_check/priority in
subprocess. No state writes, no files touched (except the ledger side-effect
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
    "command": "python <skill_root>/hooks/worker_pulse.py"}]}
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent  # kunglao-agent/
DISPATCH_RE = re.compile(
    r"\[T\s*([123])\s+tools\s*=\s*([^\]]*)\]\s*claim\s+([A-Z]+-\d+)",
    re.IGNORECASE,
)

# v1.9.29 (#38): soft stale-worker detection for the non-dispatch PostToolUse
# path. A worker is in-progress iff the LAST `status:` line (most-recent-state
# wins, same convention as lib_kunglao.scan_active_workers and
# backtrack_gate.parse_status) lowercased + dash->underscore == "in_progress".
STATUS_RE = re.compile(r"^\s*status\s*:\s*(\S+)", re.IGNORECASE | re.MULTILINE)
# #88 (D1): unanchored `status:` search for the delivery-moment check — matches
# BOTH the real status-line shape ("[12:00] step: ... | status: done") and the
# dedicated-line shape ("status: done"); last match wins (lib_kunglao convention).
FINAL_STATUS_RE = re.compile(r"status:\s*(\S+)", re.IGNORECASE)
STUCK_MIN = 20  # minutes — mirrors backtrack_gate default --stuck-min 20


def _check_stale_workers(ws: Path) -> str:
    """Soft mtime-stale detection for the non-dispatch PostToolUse path (#38).

    Scans `ws/runs/worker-status-*.md` for in-progress files whose mtime
    exceeds STUCK_MIN. Returns a human-readable message naming each stale
    worker + age, or '' if none. NEVER aborts — the hard REJECT is
    worker_budget's job (check_backtrack_gate). Any OSError / missing runs/
    dir -> '' (no crash, no false alarm)."""
    runs = ws / "runs"
    if not runs.is_dir():
        return ''
    now = time.time()
    stale = []
    try:
        for p in runs.glob("worker-status-*.md"):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            matches = STATUS_RE.findall(text)
            if not matches:
                continue
            last = matches[-1].lower().replace("-", "_")
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
            " — intervene or force a `## backtrack` block.")


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
        sys.path.insert(0, str(SKILL_DIR / "scripts"))
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
    return bool(DISPATCH_RE.search(" ".join(prompt_parts)))


def _run_py(args: list, ws: Path):
    """Run a kunglao-agent script. Args are absolute paths (cwd is the workspace,
    so relative paths would resolve against it, not the skill dir — v1.9.8
    bug caught in the first pulse test)."""
    try:
        return subprocess.run(
            [sys.executable] + args,
            capture_output=True, text=True, timeout=20,
            cwd=str(ws),
        )
    except (subprocess.SubprocessError, OSError):
        return None


def _delivery_reminder(ws: Path) -> str:
    """TASKSTOP delivery-moment reminder (#88 D1).

    When the just-completed dispatch's worker status file shows a FINAL state
    (`done` / `blocked` — LAST `status:` line wins, lib_kunglao convention),
    remind the orchestrator to TaskStop the delivered worker: a
    delivered-but-unstopped background worker holds a slot forever. Returns
    '' when no delivered worker is found (in-progress or missing = silent)."""
    runs = ws / "runs"
    if not runs.is_dir():
        return ''
    delivered = []
    try:
        for p in runs.glob("worker-status-*.md"):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            last = None
            for line in text.splitlines():
                m = FINAL_STATUS_RE.search(line)
                if m:
                    last = m.group(1).lower().replace("-", "_")
            if last in ("done", "blocked"):
                delivered.append(p.name.removeprefix("worker-status-").removesuffix(".md"))
    except OSError:
        return ''
    if not delivered:
        return ''
    return "TASKSTOP: " + ", ".join(delivered) + " delivered — TaskStop now"


def _build_pulse(ws: Path) -> tuple[str, str | None]:
    """Compact convergence snapshot: decision + next-up claim + flags.
    Returns (pulse, decision) — decision is None when convergence_check
    output is unavailable."""
    lines = ["[worker_pulse] worker completed — convergence pulse (auto):"]

    cc = _run_py([str(SKILL_DIR / "scripts" / "convergence_check.py"), str(ws), "--json"], ws)
    d = None
    if cc and cc.returncode in (0, 1, 2, 3, 4):
        try:
            d = json.loads(cc.stdout)
        except json.JSONDecodeError:
            d = None
    if d:
        lines.append(f"DECISION: {d['decision']} — {d['action']}")
        flags = []
        if d.get("stuck_workers"):
            flags.append(f"stuck={[w['worker'] for w in d['stuck_workers']]}")
        if d.get("failure_blocked"):
            flags.append(f"failure-blocked={list(d['failure_blocked'])}")
        if d.get("partial_count"):
            flags.append(f"partial={d['partial_count']}")
        if d.get("active_blockers"):
            flags.append(f"blockers={d['active_blockers']}")
        # DLQ (#36): surface quarantined (DEAD) claim count. Fail-open — a
        # missing module or register must never break the convergence pulse.
        try:
            sys.path.insert(0, str(SKILL_DIR / "scripts"))
            import dead_letter as _dl  # sibling in scripts/
            _quarantined = _dl.count_dead(ws)
            if _quarantined:
                flags.append(f"quarantined={_quarantined}")
        except Exception:
            pass
        if flags:
            lines.append("flags: " + "; ".join(flags))

    # next-up claim via priority.py
    pr = _run_py([str(SKILL_DIR / "scripts" / "priority.py"), str(ws), "--json"], ws)
    if pr and pr.returncode == 0:
        try:
            pj = json.loads(pr.stdout)
        except json.JSONDecodeError:
            pj = None
        if pj and pj.get("dispatchable"):
            top = pj["dispatchable"][0]
            lines.append(f"next up: {top['id']} (score {top['score']}) {top.get('statement', '')[:80]}")
        elif pj:
            lines.append("next up: no dispatchable claims (check DECISION above)")

    if len(lines) == 1:
        return "", (d or {}).get("decision")
    lines.append("(decide per convergence-loop; the pulse is a heuristic, not a verdict)")
    return "\n".join(lines), (d or {}).get("decision")


def main() -> int:
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
                    "additionalContext": stale_msg,
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
                    "additionalContext": "[worker_pulse] " + reminder,
                }
            }, ensure_ascii=False))
        return 0
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": pulse,
        }
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
