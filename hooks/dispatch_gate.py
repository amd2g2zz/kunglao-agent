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

#452 (派发协议结构化) — dispatch protocol:
  v1 (new, JSON):
    {"kunglao_dispatch": {"version": 1, "claim": "C-409", "tier": 1,
      "tools": [...], "agent": "ghidra-light", ...}}
  v0 (legacy, regex): [T<N> tools=a,b] claim C-NN ...
  v1 takes precedence; v0 still supported. Parsing lives in
  hooks/lib_kunglao.py:parse_dispatch (single source). On parse failure,
  this hook emits a stderr warning + hookSpecificOutput warning so a broken
  prompt is NOT silent (the pre-#452 silent-return-0 hid protocol drift).

Wiring (in .claude/settings.json PreToolUse, Agent matcher — kunglao-agent
dispatches via the Agent tool):
  {"matcher": "Agent", "hooks": [{"type": "command",
    "command": "uv run --project <skill_root> <skill_root>/hooks/dispatch_gate.py"}]}
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent  # kunglao-agent/
HOOK_STATE = Path(".hook_state.json")
# Backward-compat re-export: imports of `DISPATCH_RE` from this module keep
# working. The real parser is hooks/lib_kunglao.py:parse_dispatch which
# handles v0 (regex) + v1 (JSON).
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


def _extract_prompt_text(payload: dict) -> str:
    """Build the prompt blob from the tool_input payload shape.

    v1.9.8: handle all payload shapes (prompt / description / task / input as
    string or dict) so the gate survives whichever field carries the dispatch
    prompt."""
    tool_input = payload.get("tool_input") or {}
    prompt_parts: list[str] = []
    if isinstance(tool_input, dict):
        for k in ("prompt", "description", "task", "input"):
            v = tool_input.get(k)
            if v:
                prompt_parts.append(str(v))
        if not prompt_parts:
            prompt_parts = [str(v) for v in tool_input.values() if str(v)]
    else:
        prompt_parts = [str(tool_input)]
    return " ".join(prompt_parts)


def _parse_dispatch(text: str) -> tuple[str | None, str | None]:
    """Parse dispatch protocol (v0 regex OR v1 JSON).

    Returns (claim_id, protocol_version) or (None, reason). The shared
    parser lives in hooks/lib_kunglao.py; this thin wrapper exists so the
    gate doesn't have to know about import order / sys.path tricks."""
    try:
        sys.path.insert(0, str(SKILL_DIR / "hooks"))
        from lib_kunglao import parse_dispatch as _shared_parse
    except Exception as exc:  # pragma: no cover — defensive
        # Fallback to local regex if lib_kunglao is somehow unimportable
        m = DISPATCH_RE.search(text)
        if not m:
            return (None, f"lib_kunglao import failed ({exc!r})")
        return (m.group(3), "v0-local-fallback")
    tier, tools, claim_id = _shared_parse(text)
    if claim_id is None:
        return (None, "v0/v1 both unmatched")
    # Re-detect which protocol matched by re-running the v1 path inline
    try:
        from lib_kunglao import parse_dispatch_json
        if parse_dispatch_json(text)[2] is not None:
            return (claim_id, "v1")
    except Exception:
        pass
    return (claim_id, "v0")


def _declared_irreversible(text: str) -> bool:
    """#447 declaration-over-inference: a v1 dispatch MAY declare
    `"reversible": false` in its JSON payload. That is a STRUCTURAL,
    language-independent must-stop signal — the agent states its intent
    instead of the gate inferring it from prose (prose enumeration is
    unfinishable in any language; command grammar below is enumerable).

    Load-bearing enforcement order for must-stop:
      1. declared field (this function) — v1 only
      2. command grammar (_DISPATCH_MUST_STOP_PATTERNS) — vmrun delete /
         git push --force are commands, a finite grammar, enumerable
    Prose sniffing lives in scripts/ask_for_direction_gate.py as a
    best-effort tripwire, never load-bearing."""
    try:
        sys.path.insert(0, str(SKILL_DIR / "hooks"))
        from lib_kunglao import parse_dispatch_json
    except Exception:
        return False
    _, _, claim_id, meta = parse_dispatch_json(text)
    if claim_id is None or not isinstance(meta, dict):
        return False
    return meta.get("reversible") is False


def _warn_unparseable(claim_id: str | None, reason: str | None) -> None:
    """#452: when neither v0 nor v1 protocol matches, emit a visible signal.

    Pre-#452 the hook was silent-return-0; that hid protocol drift. Now we
    log to stderr AND inject an additionalContext warning so the orchestrator
    (and CI / logs) can see the gate did NOT recognise the dispatch."""
    print(
        "dispatch_gate: unrecognized dispatch protocol "
        f"(v0/v1 both failed: {reason})",
        file=sys.stderr,
        flush=True,
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": (
                "dispatch_gate: WARN — unrecognized dispatch protocol "
                "(v0/v1 both unmatched). Gate is INACTIVE for this dispatch. "
                "See references/dispatch-protocol.md. Add a JSON "
                '{"kunglao_dispatch":{"version":1,"claim":"C-NN","tier":N,...}} '
                "prefix to the Agent prompt."
            ),
        },
    }, ensure_ascii=False), flush=True)


# #447 Type S — irreversible-action dispatcher. English-only on principle
# (mixing languages in regex is brittle, user directive).
_DISPATCH_MUST_STOP_PATTERNS = [
    # VM / snapshot destruction
    r"\b(?:rm|delete|remove|destroy)\s+(?:vm|VM|vmx|snapshot)\b",
    r"\b(?:snapshot\s+delete|snapshot\s+revert|vmrun\s+delete)\b",
    # destructive git
    r"\bgit\s+push\s+--force\b",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\s+-fd\b",
    # public publish
    r"\b(?:public\s+publish|public\s+release|publish\s+to\s+pypi|publish\s+to\s+npm)\b",
]


def _must_stop_dispatch(prompt_text: str) -> str | None:
    """Return the first matching irreversible-action pattern, or None."""
    for pat in _DISPATCH_MUST_STOP_PATTERNS:
        m = re.search(pat, prompt_text, re.IGNORECASE)
        if m:
            return m.group(0)
    return None


def _warn_must_stop(claim_id: str | None, prompt_text: str) -> int:
    """#447 must-stop hook: emit stderr + hookSpecificOutput + HARD_PAUSE.

    Unlike scripts/ask_for_direction_gate.py which sees the orchestrator's
    PRINTED text, this hook sees the dispatch PROMPT itself — catching
    irreversible actions BEFORE the worker runs. Per
    references/agent-three-state-charter.md: must-stop events MUST HARD_PAUSE regardless
    of any other state (precedence over Type C convergence)."""
    excerpt = prompt_text[:300].replace("\n", " ")
    cid = claim_id or "(no claim)"
    print(
        f"dispatch_gate: HARD_PAUSE Type S (must-stop, #447) — irreversible "
        f"action detected in dispatch for {cid}. Refusing to dispatch.",
        file=sys.stderr,
        flush=True,
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": (
                f"dispatch_gate: HARD_PAUSE Type S (must-stop, #447). "
                f"Irreversible action detected in dispatch for {cid}. "
                f"Per references/agent-three-state-charter.md, irreversible actions "
                f"MUST be explicitly approved by the user. Refusing to "
                f"dispatch this worker. Excerpt: {excerpt!r}"
            ),
        },
    }, ensure_ascii=False), flush=True)
    return 2


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

    prompt_text = _extract_prompt_text(payload)
    claim_id, proto = _parse_dispatch(prompt_text)
    if claim_id is None:
        # #452: visible signal — gate did not recognise the dispatch
        _warn_unparseable(None, proto)
        return 0

    # #447 must-stop at dispatch time, language-independent first:
    #   1. DECLARED — v1 payload `"reversible": false` (the agent states
    #      its intent; no natural-language inference involved)
    #   2. COMMAND GRAMMAR — vmrun delete / git push --force are commands
    #      (finite grammar, enumerable), not prose
    # Fires BEFORE the failure-blocked lookup — an irreversible action in
    # a healthy claim's dispatch is just as irreversible. Single source:
    # references/agent-three-state-charter.md.
    if _declared_irreversible(prompt_text) or _must_stop_dispatch(prompt_text):
        return _warn_must_stop(claim_id, prompt_text)

    blocked = _failure_blocked_ids(ws)
    if claim_id not in blocked:
        return 0  # dispatching a healthy claim — silent

    # INJECT corrective guidance (not hard block — orchestrator can record
    # the analysis and proceed this same turn)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": (
                f"dispatch_gate: {claim_id} is failure-blocked - a prior attempt "
                f"failed and no failure_analysis is recorded. Per SKILL.md "
                f"'A failed attempt is not a negative result', run:\n"
                f"  uv run --project {SKILL_DIR} {SKILL_DIR}/scripts/failure_analysis_gate.py {ws} {claim_id}\n"
                f"answer the 3 questions (method_assumption / assumption_validity / "
                f"next_method), then re-dispatch - or dispatch a different claim. "
                f"A failed attempt is evidence the METHOD failed, not that the "
                f"behavior is absent."
            ),
        }
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
