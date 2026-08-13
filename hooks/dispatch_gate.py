#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dispatch_gate.py - narrow PreToolUse enforcement for failure-blocked claims (v1.9.7).

WHY: convergence_check / priority.py / failure_analysis_gate are all
agent-invoked — an orchestrator that skips them is unconstrained. This hook
is the ONLY enforcement that can't be ignored: it fires on the Agent tool
itself, at exactly one point — when the orchestrator tries to dispatch a
worker for a claim that is failure-blocked.

SMART = narrow + alive-only:
  - fires ONLY when the dispatch targets a failure-blocked claim
  - fires ONLY while kunglao-agent is ACTIVATED (30-min TTL, renewed by the
    orchestrator at Phase 0 / heartbeat). Expired activation = hooks sleep.
    A stale activation from a dead session cannot keep firing.
  - it injects corrective guidance (hookSpecificOutput.additionalContext),
    not a hard abort — the orchestrator can record the analysis and proceed.

Design: PreToolUse hook on Agent. Reads the dispatch prompt from the tool
input. If it matches `[T<N> tools=...] claim <C-NN>` and C-NN is in
failure_analysis_gate's BLOCKED set → inject guidance. Otherwise → exit 0
(silent). No state writes, no files touched.

Wiring (in .claude/settings.json PreToolUse, Agent matcher — kunglao-agent
dispatches via the Agent tool):
  {"matcher": "Agent", "hooks": [{"type": "command",
    "command": "python <skill_root>/hooks/dispatch_gate.py"}]}
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent  # kunglao-agent/
HOOK_STATE = Path(".hook_state.json")
DISPATCH_RE = re.compile(
    r"\[T\s*([123])\s+tools\s*=\s*([^\]]*)\]\s*claim\s+([A-Z]+-\d+)",
    re.IGNORECASE,
)


def _resolve_workspace(payload: dict) -> Path | None:
    """Same resolution as worker_budget.py: cwd → malware-analysis-workspace."""
    cwd = Path(payload.get("cwd") or payload.get("workspace") or ".")
    for base in [cwd / "malware-analysis-workspace", cwd]:
        if (base / "claim-register.yaml").exists():
            return base
    return None


def _kunglao_active(ws: Path) -> bool:
    """kunglao-agent active iff dispatch_gate in active_hooks AND not expired
    (30-min TTL, renewed by the orchestrator at Phase 0 / heartbeat).

    v1.9.7 default-inactive for hooks: no state file → hooks sleep. The
    orchestrator must explicitly activate at Phase 0, and renew every
    30 min, or the hooks go quiet — activation is a real liveness signal."""
    state_path = ws / HOOK_STATE
    if not state_path.exists():
        return False
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    # expiry check first — a stale activation must not fire
    expires = state.get("expires_at")
    if expires:
        try:
            exp = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            if datetime.now(tz=timezone.utc) > exp:
                return False  # expired — hooks sleep
        except (ValueError, TypeError):
            return False
    active = state.get("active_hooks", [])
    paused = state.get("paused_hooks", [])
    if "dispatch_gate" in paused:
        return False
    if "dispatch_gate" in active:
        return True
    return False


def _failure_blocked_ids(ws: Path) -> set:
    """Claims with a failed attempt but no current failure_analysis."""
    try:
        sys.path.insert(0, str(SKILL_DIR / "scripts"))
        import failure_analysis_gate as fag
        return {b["claim_id"] for b in fag.scan_workspace(ws) if b.get("state") == "BLOCKED"}
    except Exception:
        return set()


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0

    ws = _resolve_workspace(payload)
    if ws is None:
        return 0  # not a kunglao-agent workspace — silent

    if not _kunglao_active(ws):
        return 0  # kunglao-agent not activated or expired — hooks sleep

    # Extract the dispatch description. kunglao-agent dispatches workers via the
    # Agent tool (worker_budget is wired on the Agent matcher); the description
    # lives in the prompt field. v1.9.8: handle all payload shapes (prompt /
    # description / task / input as string or dict) so the gate survives
    # whichever field carries the dispatch prompt.
    tool_input = payload.get("tool_input") or {}
    prompt_parts = []
    if isinstance(tool_input, dict):
        for k in ("prompt", "description", "task", "input"):
            v = tool_input.get(k)
            if v:
                prompt_parts.append(str(v))
        if not prompt_parts:
            prompt_parts = [str(v) for v in tool_input.values() if str(v)]
    else:
        prompt_parts = [str(tool_input)]
    prompt_text = " ".join(prompt_parts)
    m = DISPATCH_RE.search(prompt_text)
    if not m:
        return 0  # not a claim dispatch — silent

    claim_id = m.group(3)
    blocked = _failure_blocked_ids(ws)
    if claim_id not in blocked:
        return 0  # dispatching a healthy claim — silent

    # INJECT corrective guidance (not hard block — orchestrator can record
    # the analysis and proceed this same turn)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": (
                f"dispatch_gate: {claim_id} is failure-blocked — a prior attempt "
                f"failed and no failure_analysis is recorded. Per SKILL.md "
                f"'A failed attempt is not a negative result', run:\n"
                f"  python {SKILL_DIR}/scripts/failure_analysis_gate.py {ws} {claim_id}\n"
                f"answer the 3 questions (method_assumption / assumption_validity / "
                f"next_method), then re-dispatch — or dispatch a different claim. "
                f"A failed attempt is evidence the METHOD failed, not that the "
                f"behavior is absent."
            ),
        }
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
