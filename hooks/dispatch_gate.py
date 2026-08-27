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

#496 decision teeth (value selection gets enforcement on this face):
  - top-1: dispatching a non-top-1 claim (rank >= 2 under
    worker_budget.check_priority — the single ranking source, #499
    authority = priority_ratio) without an `agent-reasoning:` prefix
    REJECTs; with the reason it passes and leaves a
    priority_deviation trace in the unified log (exact copy of the #310
    agenttype-deviation structure).
  - capability card: the target claim's (or its obstacle_for parent's)
    #495 validated_capability mentions tool family F, the dispatch
    declares a disjoint family, and the prompt shows no
    `capability-disproof: <family>` -> REJECT (disprove the card first —
    trajectory-1 replay: frida validated, switching to xposed needs the
    frida failure shown). FAIL_OPEN when no card / no known families.
  - strategy log: a passing dispatch carrying `[strategy <id>]` appends
    the dispatch row consumed by priority_ratio's novelty (opt-in).

#452 (派发协议结构化) — dispatch protocol:
  v1 (new, JSON):
    {"kunglao_dispatch": {"version": 1, "claim": "C-409", "tier": 1,
      "tools": [...], "agent": "ghidra-light", ...}}
  v0 (legacy, regex): [T<N> tools=a,b] claim C-NN ...
  v1 takes precedence; v0 still supported. Parsing lives in
  hooks/lib_kunglao.py:parse_dispatch (single source). On parse failure,
  this hook emits a stderr warning + hookSpecificOutput warning so a broken
  prompt is NOT silent (the pre-#452 silent-return-0 hid protocol drift).

#760 (I1 dispatch tool-face) — the dispatched `tools=` rack is mechanically
  validated against the target agent's frontmatter allowedTools (subset,
  wildcard-aware, case-insensitive) AND must keep a write-capable tool
  (Write/Edit, §1c file contract floor). Agent identity: payload
  subagent_type/name or v1 meta.agent; no identity / unknown agent -> skip.
  Rides the #567 structural corridor: fires before activation — an
  unfulfillable rack (mm_x86: ida-pro-mcp only) must not wait for a session.

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

import yaml

try:  # normal load paths (hook subprocess: script dir; pytest: pythonpath)
    from _path_hygiene import on_path, scripts_on_path  # #671 authority
except ImportError:  # by-path exec WITHOUT hooks/ on sys.path — the
    # subprocess-driver pattern (tests/test_failopen_emit loads this file
    # via spec_from_file_location inside a python tmp/driver.py whose
    # sys.path has the driver dir, not hooks/). Self-bootstrap by path,
    # registered under the canonical name so later imports share it.
    import importlib.util as _ilu
    _hyg_spec = _ilu.spec_from_file_location(
        "_path_hygiene", Path(__file__).resolve().parent / "_path_hygiene.py")
    _hyg = _ilu.module_from_spec(_hyg_spec)
    sys.modules["_path_hygiene"] = _hyg
    _hyg_spec.loader.exec_module(_hyg)
    on_path = _hyg.on_path
    scripts_on_path = _hyg.scripts_on_path

SKILL_DIR = Path(__file__).resolve().parent.parent  # kunglao-agent/
HOOK_STATE = Path(".hook_state.json")
# #603: append-only top-1 REJECT ledger — one JSON row per REJECT, the
# durable face of `_top1_enforcement`'s rc=2 path (pre-#603 the REJECT was
# trace-only; an orchestrator looping on the same deviation accumulated
# rejections with nothing on disk to count). Consumed by
# scripts/kunglao_resume.py; NEVER wired into the #604 retry counter
# (v0.1.3 adjudication — REJECT is pre-dispatch, worker attribution is
# structurally unreliable).
GATE_REJECTIONS_LOG = Path("runs/gate-rejections.jsonl")
# Backward-compat re-export: imports of `DISPATCH_RE` from this module keep
# working. The real parser is hooks/lib_kunglao.py:parse_dispatch which
# handles v0 (regex) + v1 (JSON).
DISPATCH_RE = re.compile(
    r"\[T\s*([123])\s+tools\s*=\s*([^\]]*)\]\s*claim\s+([A-Z]+-\d+)",
    re.IGNORECASE,
)


def _resolve_workspace(payload: dict) -> Path | None:
    """cwd → <layout.workspace_dir> — the layout names come from the env
    manifest (#450 single source; hooks/dispatch_gate.py +
    scripts/convergence_check.py + hooks/lib_kunglao.py used to hardcode
    them). Absent manifest → DEFAULT_LAYOUT = the pre-#450 literals,
    discovery behavior byte-identical."""
    cwd = Path(payload.get("cwd") or payload.get("workspace") or ".")
    try:
        # #671: scoped membership (no leaked sys.path entry even when
        # _resolve_workspace is called repeatedly in-process — tests,
        # embedders); the in-process existence check is now the hygiene
        # module's concern.
        with scripts_on_path():
            import env_manifest
    except ImportError as exc:  # broken install, not a degraded mode (#444 posture)
        raise RuntimeError(
            f"env manifest module missing: {SKILL_DIR / 'scripts' / 'env_manifest.py'} — "
            "hooks/ and scripts/ ship together; reinstall the kunglao-agent "
            "skill") from exc
    layout = env_manifest.layout_conventions(cwd)
    for base in [cwd / layout.workspace_dir, cwd]:
        if (base / layout.claim_register).exists():
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
        with scripts_on_path():  # #671 scoped membership
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
        with on_path(SKILL_DIR / "hooks"):  # #671 scoped membership
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
        with on_path(SKILL_DIR / "hooks"):  # #671 scoped membership
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


# ===================== #496 decision teeth =====================

# ③ strategy dispatch marker: `[strategy <id>]` anywhere in the prompt.
STRATEGY_MARKER_RE = re.compile(r"\[strategy\s+([A-Za-z0-9._-]+)\]")
STRATEGY_LOG = "runs/strategy-log.jsonl"
# #496 review F4: the ledger used to append unbounded (every marked
# dispatch +1 row, from_workspace re-reads the whole file). Cap: before
# each dispatch row is written the file is re-read and truncated to the
# most recent STRATEGY_LOG_MAX rows (read-truncate-write — idempotent, an
# already-short file keeps its rows verbatim and in order).
STRATEGY_LOG_MAX = 200


def _reject_with_guidance(name: str, msg: str, fix: str) -> int:
    """#496: REJECT with guidance — the exact structure worker_budget._reject
    and _warn_must_stop already use: stderr `REJECT <name>` summary + stdout
    hookSpecificOutput.additionalContext carrying a concrete fix path +
    exit 2 (block the Agent call)."""
    print(f"REJECT {name}: {msg}", file=sys.stderr, flush=True)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": (
                f"dispatch_gate: REJECT {name} (#496). {msg}\n\nHow to fix:\n{fix}"
            ),
        },
    }, ensure_ascii=False), flush=True)
    return 2


def _emit_trace(ws: Path, action: str, claim_id: str, detail: str,
                exit_code: int | None = None) -> None:
    """Deviation/disproof/REJECT trace into the unified event log (kunglao_log,
    the #459 face #461 dispatch events already use — self_redirects.jsonl
    is the #447 ask-back VIOLATION counter and must stay unpolluted).
    Action words are registered in event_taxonomy.EMIT_ACTIONS; exit_code
    carries the gate's rc on REJECT faces (#459). Logging never breaks the
    gate: fail-open, stderr note only."""
    try:
        with scripts_on_path():  # #671 scoped membership
            from kunglao_log import emit
        emit(ws, "hook:dispatch_gate", action, claim=claim_id, detail=detail,
             exit=exit_code)
    except Exception as exc:  # noqa: BLE001 — a trace must never block dispatch
        print(f"dispatch_gate: trace emit failed ({action}: {exc!r})",
              file=sys.stderr, flush=True)


def _top1_enforcement(ws: Path, claim_id: str, prompt_text: str) -> int | None:
    """① #496: top-1 enforcement — exact copy of the #310 agenttype-deviation
    pattern with the ranking source swapped for worker_budget.check_priority
    (which ranks by priority_ratio, the #499 authority — reusing it keeps
    this hook and worker_budget's devreason audit on ONE ranking, never two).

    deviated (rank >= 2) + no `agent-reasoning:` prefix -> REJECT (exit 2);
    with the prefix -> pass + stderr `TOP1 (deviation recorded)` +
    priority_deviation trace. rank-None / audit unavailable -> no REJECT
    (FAIL_OPEN — a broken gate must not block dispatch; the failure-blocked
    slice keeps its own #495 injection path)."""
    try:
        with on_path(SKILL_DIR / "hooks"):  # #671 scoped membership
            from worker_budget import check_priority
    except Exception as exc:  # noqa: BLE001 — scorer wiring unavailable -> fail open
        # #569 AUDIT: the gate is being bypassed silently — leave a trace so
        # post-mortem can see the FAIL_OPEN path was taken. detail carries
        # the exception class so the post-mortem can distinguish scorer
        # unavailable from audit crash without re-reading the source.
        _emit_trace(ws, "top1_fail_open", claim_id,
                    f"reason=scorer_unavailable; exc={type(exc).__name__}")
        return None
    try:
        _ok, msg, deviated = check_priority(
            ws / "claim-register.yaml", ws / "claim_deps.yaml",
            ws / "task_spec.yaml", claim_id, ws)
    except Exception as exc:  # noqa: BLE001 — audit crash -> fail open
        # #569 AUDIT: same as above — the audit itself crashed, the gate
        # fails open, but the audit log must record the bypass.
        _emit_trace(ws, "top1_fail_open", claim_id,
                    f"reason=audit_crash; exc={type(exc).__name__}: {exc}")
        return None
    if not deviated:
        if msg:
            print(f"PRIORITY: {msg}", file=sys.stderr, flush=True)
        return None
    if "agent-reasoning:" in (prompt_text or "").lower():
        print(f"TOP1 (deviation recorded): {msg}", file=sys.stderr, flush=True)
        _emit_trace(ws, "priority_deviation", claim_id, msg)
        return None
    # #459: the REJECT face reaches the unified log too (the excused side
    # already traces; a blocked deviation is the event the post-mortem needs)
    _emit_trace(ws, "top1_reject", claim_id, msg, exit_code=2)
    # #603: a REJECT must be DURABLE, not trace-only. Pre-#603 this face
    # emitted a stderr/stdout trace and nothing else — an orchestrator
    # looping on the same deviation accumulated rejections silently. One
    # side effect, fail-open (bookkeeping must never turn a REJECT into a
    # silent pass; a broken append degrades to a stderr note only):
    #   one row appended to runs/gate-rejections.jsonl — the durable
    #   rejection ledger (append-only JSONL, same shape discipline as
    #   scripts/gate_telemetry.py), consumed by scripts/kunglao_resume.py.
    # ADJUDICATION (v0.1.3): this is the ONLY side effect. REJECT is a
    # PRE-DISPATCH event — worker attribution here is structurally
    # unreliable (the time-fallback key never accumulates; agent-name
    # attribution would trip the #604 MAX_RETRIES breaker on the worker's
    # next COMPLIANT dispatch). runs/.retry-counter.yaml belongs to the
    # orchestrator's silent-failure counting (#604) and must NOT be wired
    # into the REJECT path — semantic contamination.
    try:
        row = {
            "ts": datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
                    .replace("+00:00", "Z"),
            "gate": "top1",
            "claim": claim_id,
            "msg": msg,
            "exit_code": 2,
        }
        ledger = ws / GATE_REJECTIONS_LOG
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with open(ledger, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"dispatch_gate: gate-rejections append failed ({exc!r})",
              file=sys.stderr, flush=True)
    return _reject_with_guidance(
        "top1", msg,
        "add `agent-reasoning: <why this claim instead of the ranked #1>` "
        "to the dispatch prompt (the deviation must be recorded, not "
        "silently skipped — same discipline as the #310 agenttype gate), "
        "or dispatch the top-ranked claim.")


def _mcp_prefix_gate(prompt_text: str) -> int | None:
    """#567 SECURITY: MCP tool prefix enforcement.

    Rejects dispatch payloads declaring any tool whose name carries a
    forbidden MCP prefix (mcp__unknown__*, mcp__external__*). The helper
    is the single source in hooks/lib_kunglao.py:check_mcp_prefix —
    mirrors the HOST_FORBIDDEN_TOOLS posture in worker_budget.py. None
    (pass-through) when the dispatch declares no tools or only sanctioned
    ones. Returns rc=2 with REJECT guidance on the first offender."""
    try:
        with on_path(SKILL_DIR / "hooks"):  # #671 scoped membership
            from lib_kunglao import check_mcp_prefix, parse_dispatch as _shared_parse
    except Exception:  # noqa: BLE001 — helper unavailable -> fail open
        return None
    try:
        tier, tools, _claim_id = _shared_parse(prompt_text or "")
    except Exception:  # noqa: BLE001 — unparseable tools -> open
        return None
    if not tools:
        return None
    for tool in tools:
        allowed, reason = check_mcp_prefix(tool)
        if not allowed:
            return _reject_with_guidance(
                "mcp_prefix", reason,
                "use only mcp__kunglao__* MCP tools in this workspace — "
                "add new MCP namespaces to lib_kunglao.MCP_FORBIDDEN_PREFIXES "
                "intentionally, never bypass via unknown prefixes.")
    return None


def _capability_guard(ws: Path, claim_id: str, prompt_text: str) -> int | None:
    """②(a) #496: capability card — a validated capability in hand (the
    #495 artifact, read via priority_ratio.EvidenceView) constrains tool
    choice. Switching to a disjoint declared tool family REJECTs unless the
    prompt shows the disproof (`capability-disproof: <family>`); an excused
    switch passes and leaves a capability_switch trace. The card scope is
    the target claim PLUS its obstacle_for parent — the trajectory-1 pivot
    onto the promoted obstacle claim stays covered. FAIL_OPEN when the
    scorer, the register or the card is unavailable."""
    try:
        with scripts_on_path():  # #671 scoped membership
            import priority_ratio as pr
    except Exception:  # noqa: BLE001 — scorer unavailable -> fail open
        return None
    tools: list[str] = []
    try:
        with on_path(SKILL_DIR / "hooks"):  # #671 scoped membership
            from lib_kunglao import parse_dispatch
            tools = parse_dispatch(prompt_text or "")[1]
    except Exception:  # noqa: BLE001 — unparseable tools -> no families -> open
        tools = []
    claim_ids = {claim_id}
    try:
        reg = yaml.safe_load(
            (ws / "claim-register.yaml").read_text(encoding="utf-8")) or {}
        target = next((c for c in (reg.get("claims") or [])
                       if c.get("id") == claim_id), None)
        parent = (target or {}).get("obstacle_for")
        if parent:
            claim_ids.add(str(parent))
    except Exception:  # noqa: BLE001 — register unreadable -> card scope is the claim
        pass
    try:
        evidence = pr.EvidenceView.from_workspace(ws)
    except Exception:  # noqa: BLE001 — artifact scan failure -> fail open
        return None
    v = pr.capability_switch_violation(claim_ids, tools, prompt_text, evidence)
    if v is None:
        # trace the EXCUSED switch: a disproof marker naming a validated
        # family the dispatch moved away from (cold path, recomputed here so
        # the pure judgment stays single-purpose)
        if "capability-disproof:" in (prompt_text or "").lower():
            cap_fams: set[str] = set()
            for cid, cap in evidence.validated_capabilities:
                if cid in claim_ids:
                    cap_fams |= pr.tool_families_from_text(cap)
            disp_fams = pr.tool_families_from_tools(tools)
            if cap_fams and disp_fams and not (cap_fams & disp_fams):
                print(f"CAPABILITY (disproof recorded): {claim_id} switching "
                      f"from validated {sorted(cap_fams)} to "
                      f"{sorted(disp_fams)}", file=sys.stderr, flush=True)
                _emit_trace(ws, "capability_switch", claim_id,
                            f"disproof shown; validated={sorted(cap_fams)} "
                            f"dispatch={sorted(disp_fams)}")
        return None
    # #459: the capability REJECT face reaches the unified log (trajectory-1
    # pivots must be visible in the event stream, not stderr-only)
    _emit_trace(ws, "capability_reject", claim_id,
                f"validated={v['validated_families']} "
                f"dispatch={v['dispatch_families']}", exit_code=2)
    return _reject_with_guidance(
        "capability",
        f"{claim_id} has a validated capability in hand "
        f"({v['capability'][:120]}) but the dispatch declares a different "
        f"tool family {v['dispatch_families']} (validated: "
        f"{v['validated_families']})",
        "show the disproof first — add `capability-disproof: <family> "
        "(why the validated tool family failed)` to the dispatch prompt "
        "(the #495 analysis already carries the obstacle evidence; the "
        "marker is you SHOWING the card, trajectory-1: switching off "
        "validated frida requires the frida failure) — or keep dispatching "
        "the validated family.")


def _plan_drift_auto(ws: Path, claim_id: str, prompt_text: str) -> int | None:
    """#602: plan-drift auto-integration wire-up for L621 dispatch path entry.

    Shells out to scripts/plan_drift_detector.py --auto and translates its
    exit code into a dispatch-gate response:
      - exit 2 (drift-severe, 1+ non-WARN drift)     -> return 2 (BLOCKED)
      - exit 3 (WARN-only, STALE_PLAN_ON_NEW_EVIDENCE) -> return 3 (SATURATED)
      - exit 0 (no drift)                            -> return None (fall through)
      - any other / missing / unparseable workspace  -> return None (fail-open)

    NON-FATAL by design: a false-positive is acceptable — the operator
    can re-dispatch. This is a PreToolUse safety net, NOT a hard gate;
    the BLOCKED escalation only fires on REAL drift-severe events
    (non-WARN classes: ORPHAN_CLAIM / STALE_PLAN_ENTRY / MISSING_DEP_LINK /
    UNANSWERED_QUESTION / STALE_NEXT_STEP / UNVERIFIED_EVIDENCE).

    The 5-second timeout mirrors the dispatch-gate hook posture (a hung
    child process must NOT stall the orchestrator); on timeout we fail-open
    (None) so an environment where plan_drift_detector is slow doesn't
    break dispatch.
    """
    import subprocess as _sp
    script = SKILL_DIR / "scripts" / "plan_drift_detector.py"
    if not script.exists():
        return None
    try:
        proc = _sp.run(
            [sys.executable, str(script), str(ws), "--auto"],
            capture_output=True, text=True, timeout=5,
        )
    except (_sp.TimeoutExpired, FileNotFoundError, OSError):
        # NON-FATAL: timeout / spawn failure / missing interpreter -> open
        return None
    except Exception:  # noqa: BLE001 — last-resort fail-open
        return None
    rc = proc.returncode
    if rc == 2:
        # drift-severe -> BLOCKED. Print so the operator tail can see it.
        try:
            tail = (proc.stdout or "").strip().splitlines()[-1] if proc.stdout else ""
        except Exception:
            tail = ""
        print(f"dispatch_gate: plan-drift auto BLOCKED ({claim_id}): {tail}",
              file=sys.stderr, flush=True)
        return 2
    if rc == 3:
        # drift-warning -> SATURATED. Visible but not REJECT.
        print(f"dispatch_gate: plan-drift auto SATURATED ({claim_id}): "
              "WARN-only, observe-first",
              file=sys.stderr, flush=True)
        return 3
    # rc 0 (no drift) or any unexpected -> fall through
    return None


def _log_strategy_dispatch(ws: Path, claim_id: str, prompt_text: str) -> None:
    """③ #496: append the strategy dispatch row on the PASS path — the only
    writer the strategy-novelty interface needs (opt-in: no
    `[strategy <id>]` marker, no row). attempts_at_snapshot is the claim's
    current promotion_attempts, so a later #495 analysis with a higher
    covers_attempt counts as a same-strategy failure. Fail-open."""
    m = STRATEGY_MARKER_RE.search(prompt_text or "")
    if not m:
        return
    snapshot = 0
    try:
        reg = yaml.safe_load(
            (ws / "claim-register.yaml").read_text(encoding="utf-8")) or {}
        target = next((c for c in (reg.get("claims") or [])
                       if c.get("id") == claim_id), None)
        snapshot = int((target or {}).get("promotion_attempts") or 0)
    except Exception:  # noqa: BLE001 — unreadable register: snapshot 0, row kept
        snapshot = 0
    row = {
        "ts": datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
                .replace("+00:00", "Z"),
        "event": "dispatch",
        "strategy": m.group(1),
        "claim": claim_id,
        "attempts_at_snapshot": snapshot,
    }
    try:
        path = ws / STRATEGY_LOG
        path.parent.mkdir(parents=True, exist_ok=True)
        kept: list[str] = []
        if path.exists():
            kept = [ln for ln in
                    path.read_text(encoding="utf-8", errors="replace").splitlines()
                    if ln.strip()]
        kept = kept[-STRATEGY_LOG_MAX:]
        kept.append(json.dumps(row, ensure_ascii=False))
        path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"dispatch_gate: strategy-log write failed ({exc!r})",
              file=sys.stderr, flush=True)


# #567 SECURITY: MCP tool prefix enforcement.
DISPATCH_MCP_DOC = "mcp__unknown__*, mcp__external__*"  # doc anchor only

# #760 I1: dispatch tools= mechanical validation against the target agent's
# frontmatter allowedTools (+ the §1c write-capable-tool floor). The mm_x86
# incident: an orchestrator narrowed a worker's rack to `ida-pro-mcp` free
# text zero-checked — no Bash/Write -> the §1c file contract was unfulfillable
# and the LEARN->TRY ladder got abused into "use IDA in-process python as
# shell". The allowedTools racks are skill-owned static contracts in
# agents/*.md, so like #567 this face is STRUCTURAL: it fires before the
# activation check (a forbidden tool rack is not a session-level concern).
#
# Agent identity source order: payload.tool_input.subagent_type ->
# payload.tool_input.name (worker_budget_sinks reads .name today) -> v1 JSON
# meta.agent. No identity / unknown agents/<name>.md -> validation skips and
# the pre-#760 path is untouched (legacy v0 text-only payloads never carry an
# agent name; every historical dispatch-gate test stays byte-green).

_FRONTMATTER_RE_760 = re.compile(r"\A---\s*\n(.*?)\n---", re.DOTALL)
WRITE_CAPABLE_TOOLS = ("write", "edit")


def _agent_allowed_tools(agent_name: str | None) -> list[str] | None:
    """agents/<name>.md frontmatter allowedTools -> list (None if unknown).

    Local twin of route_capability._parse_frontmatter: hooks must not depend
    on scripts/ private API (#671 boundary); yaml is already imported here."""
    if not agent_name:
        return None
    path = SKILL_DIR / "agents" / f"{agent_name}.md"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = _FRONTMATTER_RE_760.match(text)
    if not m:
        return None
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    tools = data.get("allowedTools")
    if isinstance(tools, str):
        return [t.strip() for t in tools.split(",") if t.strip()]
    if isinstance(tools, list):
        return [str(t).strip() for t in tools if str(t).strip()]
    return None


def _resolve_dispatch_agent(payload: dict, prompt_text: str) -> str | None:
    """Dispatched agent identity from the Agent tool payload or v1 meta."""
    tool_input = payload.get("tool_input") or {}
    if isinstance(tool_input, dict):
        for key in ("subagent_type", "name"):
            v = tool_input.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
    try:
        with on_path(SKILL_DIR / "hooks"):  # #671 scoped membership
            from lib_kunglao import parse_dispatch_json
        _, _, _claim_id, meta = parse_dispatch_json(prompt_text or "")
        if isinstance(meta, dict):
            v = meta.get("agent")
            if isinstance(v, str) and v.strip():
                return v.strip()
    except Exception:  # noqa: BLE001 — metadata best-effort only
        pass
    return None


def _tool_matches_allowed(pattern: str, tool: str) -> bool:
    """One declared tool vs one allowedTools pattern.

    - wildcard pattern `x*`   -> startswith prefix match;
    - plain pattern           -> case-insensitive full equality (historical
      v0 racks self-restrict with lowercase names: `grep` <-> Grep)."""
    p = pattern.strip()
    t = tool.strip()
    if p.endswith("*"):
        return bool(p[:-1]) and t.lower().startswith(p[:-1].lower())
    return t.lower() == p.lower()


def _tools_contract_violation(declared_tools: list[str],
                              agent_name: str) -> str | None:
    """Pure judgment: first §760 violation message, or None when clean.

    - empty rack: no restriction declared -> nothing to enforce (the agent
      keeps its full frontmatter rack; §1c satisfiable);
    - subset rule: every declared tool must resolve into allowedTools;
    - write floor: a non-empty rack MUST contain Write or Edit (§1c file
      contract — Bash indirect writes do not count)."""
    if not declared_tools:
        return None
    allowed = _agent_allowed_tools(agent_name) or []
    offending = [
        t for t in declared_tools
        if not any(_tool_matches_allowed(p, t) for p in allowed)
    ]
    if offending:
        return (
            f"tool {offending[0]} not in {agent_name} allowedTools "
            f"(dispatched rack declares {len(offending)} of "
            f"{len(declared_tools)} unknown names)")
    lowered = {t.lower() for t in declared_tools}
    if not any(w in lowered for w in WRITE_CAPABLE_TOOLS):
        return (
            f"missing write-capable tool (§1c) — the rack "
            f"[{', '.join(declared_tools)}] cannot fulfil the worker file "
            f"contract (facts/Fxxx.md + worker-status)")
    return None


def _tools_rack_gate(payload: dict, prompt_text: str) -> int | None:
    """#760 I1: tools= ⊆ <agent>.allowedTools + §1c write-capable floor.

    Skips silently (None) when the dispatch carries no agent identity or the
    agent file is unknown; REJECTs (rc=2, fix guidance) otherwise."""
    try:
        with on_path(SKILL_DIR / "hooks"):  # #671 scoped membership
            from lib_kunglao import parse_dispatch
        _, declared_tools, _claim = parse_dispatch(prompt_text or "")
    except Exception:  # noqa: BLE001 — unparseable protocol -> pre-existing warn face
        return None
    agent_name = _resolve_dispatch_agent(payload, prompt_text)
    if agent_name is None or _agent_allowed_tools(agent_name) is None:
        return None
    violation = _tools_contract_violation(list(declared_tools or []),
                                          agent_name)
    if violation is None:
        return None
    return _reject_with_guidance(
        "tools_rack", violation,
        f"narrow the rack to tools inside agents/{agent_name}.md "
        f"allowedTools AND keep at least one of Write/Edit so the §1c file "
        f"contract (worker-status + facts/Fxxx.md) stays fulfilable — e.g. "
        f"`[T<N> tools=Read,Write,Grep]`. A rack without a file writer "
        f"(mm_x86: ida-pro-mcp only) forces the worker to fake files through "
        f"in-process interpreters; that output is untrusted by design.")


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0

    ws = _resolve_workspace(payload)
    if ws is None:
        # Even with no workspace resolution, MCP prefix gate must still
        # REJECT forbidden namespaces — the prefix is a structural policy,
        # not a workspace-bound concern. Issue #567.
        try:
            prompt_text = _extract_prompt_text(payload)
        except Exception:  # noqa: BLE001 — malformed payload -> no-op
            return 0
        claim_id, _proto = _parse_dispatch(prompt_text)
        if claim_id is None:
            return 0
        rc = _mcp_prefix_gate(prompt_text)
        if rc is not None:
            return rc
        # #760 I1: same structural corridor as the prefix gate above.
        return _tools_rack_gate(payload, prompt_text)

    # #567 SECURITY: MCP prefix gate runs BEFORE activation check — a
    # forbidden MCP namespace is a structural policy violation, NOT a
    # session-level concern. The gate sleeps for nothing else; it must
    # not sleep for `mcp__unknown__*` / `mcp__external__*`. Hooks may not
    # be activated and the prefix must still REJECT.
    prompt_text = _extract_prompt_text(payload)
    claim_id, proto = _parse_dispatch(prompt_text)
    if claim_id is not None:
        rc = _mcp_prefix_gate(prompt_text)
        if rc is not None:
            return rc
        # #760 I1: tools= ⊆ allowedTools + §1c write floor — the allowedTools
        # racks are skill-owned static contracts, so this face rides the SAME
        # structural corridor (fires pre-activation; unknown agent -> skip).
        rc = _tools_rack_gate(payload, prompt_text)
        if rc is not None:
            return rc

    if not _kunglao_active(ws):
        return 0  # kunglao-agent not activated or expired — hooks sleep

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
    if claim_id in blocked:
        # INJECT corrective guidance (not hard block — orchestrator can
        # record the analysis and proceed this same turn). The #495 slice
        # keeps its own response; the #496 teeth below never hijack it
        # (a failure-blocked claim is rank-None under check_priority).
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

    # #602: plan-drift auto-integration — runs BEFORE the existing dispatch
    # block. Drift-severe -> BLOCKED (rc=2); drift-warning -> SATURATED
    # (rc=3); no drift -> None (fall through). NON-FATAL: false-positive is
    # acceptable (operator can re-dispatch).
    rc = _plan_drift_auto(ws, claim_id, prompt_text)
    if rc is not None:
        return rc

    # #496 decision teeth, in order: top-1 first (the most fundamental
    # deviation), then the capability card, then the strategy log on the
    # pass path. Each REJECTs (exit 2) or returns None to fall through.
    rc = _top1_enforcement(ws, claim_id, prompt_text)
    if rc is not None:
        return rc
    rc = _capability_guard(ws, claim_id, prompt_text)
    if rc is not None:
        return rc
    # #567 SECURITY: MCP prefix gate runs BEFORE this point (see main()
    # ordering) — a forbidden MCP namespace is a structural violation,
    # not a session-level concern, so it cannot be deferred to the
    # activated path.
    _log_strategy_dispatch(ws, claim_id, prompt_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
