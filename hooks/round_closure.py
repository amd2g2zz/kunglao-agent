#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hooks/round_closure.py — SubagentStop wiring (event-wakeup topology,
issue 434): the round-closure event feed + the kernel closure faces.

Between-turns wakes come from worker completion notifications — but the
closure itself left no ledger row the decision faces could consume (the
lifecycle pipe existed with no live producer on this event). This hook
appends ONE closure event row per SubagentStop: a lifecycle_completed
transition (kunglao_log.emit_lifecycle — the established subagent
lifecycle face) carrying the session identity in detail.

Since issue 462 the closure event is ALSO the production host of the
kernel's round-closure faces (#429 §6: Stop(worker) IS the round
closure): W1 composes + versions ONE round-strategy object per decision
event (the compose single-point's host), and W6 builds + drains the T2
unblocking-value priority queue (no longer eval-only). Since the online
distillation capability the closure also scans the report surface for
shelf-miss signals (marker / unknown-format probe) and stamps the
trigger state the orchestrator's tick consumes.

Issue #690 makes the closure the SETTLEMENT POINT (step := one subagent
completion): the first kernel face settles the pending step — the
session's tool-call rows aggregate into one step-record/2 row, the
transition closes via incremental_reward.append_transition (the
production caller that did not exist before), and a branch_budget.wall_s
overrun lands in attributed-waste — BEFORE compose decides, so the
strategy object always sees post-settlement state (settle -> update ->
decide). No pending step (a non-worker subagent stop) writes nothing.

The closure ALSO carries the RL digest face (round-closure visibility):
one ``{"systemMessage": "RL: lead=..."}`` line on stdout — the Claude
Code user-facing hook message field — so the operator's scrolling
transcript shows what the RL just decided (method lead in force + its
age + the last settlement) without opening runs/*.jsonl by hand. The
line is rate-limited per DECISION (scripts/rl_digest.py owns the marker
and the template): an unchanged round stays silent, and none in force
renders nothing at all.

Pure-closure posture, fail-open double cage: any error -> rc 0, silent.
A closure observation must never disturb the subagent's own stop path.
"""
from __future__ import annotations
# The canonical warn — ONE implementation (process-wide dedupe per
# (op, reason) + the ledger face). The stderr-only fallback is the
# partial-deploy lifeline; production imports kunglao_log.
try:
    from _path_hygiene import ensure_scripts_path as _esp406
    _esp406()
    from kunglao_log import warn
except Exception:  # noqa: BLE001 — fail-open lifeline, never block the hook
    def warn(op: str, reason: str) -> None:
        print(f"[kunglao-agent] WARN (fail-open): {op}: {reason}",
              file=sys.stderr)
import json
import sys
from pathlib import Path

from _path_hygiene import load_hooks_lib, scripts_on_path  # #671 authority

CLOSURE_ACTOR = "subagent:stop"


def _resolve_workspace(payload: dict) -> Path | None:
    """Workspace markers (claim-register.yaml / .hook_state.json) under
    cwd or cwd/malware-analysis-workspace — the deployed convention."""
    cwd = Path(payload.get("cwd") or payload.get("workspace") or ".")
    for base in [cwd / "malware-analysis-workspace", cwd]:
        if (base / "claim-register.yaml").exists() \
                or (base / ".hook_state.json").exists():
            return base
    return None


#: the settle-vocabulary mirror of rlvr.crystallize.FAIL_OUTCOMES /
#: worker_budget_sinks.DISPATCH_FAILURE_STATUSES — owned per tree (a
#: hooks→scripts import at module level would re-bind by ambient
#: sys.path order).
_FAILURE_OUTCOMES = frozenset({"blocked", "failed", "error"})


def _worker_outcome(ws, pending) -> str:
    """The settled step's outcome from the worker's OWN status log (the
    last ``status:`` token, the single parse point in the hooks lib),
    mapped onto the settle vocabulary: done -> completed; the dispatch
    failure words ride as-is. Retried workers reopen suffixed logs
    (``worker-status-<claim>-<suffix>.md``) — the newest hit wins.
    Fail-open: no pending step, an unreadable log, or an unknown token
    settles as completed."""
    if not pending:
        return "completed"
    try:
        claim = str(pending.get("claim") or "")
        # the exact log plus its retry-suffixed reopens
        # (worker-status-<claim>-<suffix>.md); NEWEST log wins — a
        # retry's reopened log is the worker's final word.
        runs = ws / "runs"
        candidates = [runs / f"worker-status-{claim}.md"]
        candidates.extend(runs.glob(f"worker-status-{claim}-*.md"))
        candidates = sorted(
            (p for p in candidates if p.is_file()),
            key=lambda p: p.stat().st_mtime, reverse=True)
        for path in candidates:
            last = load_hooks_lib().parse_worker_status(
                path.read_text(encoding="utf-8", errors="replace"))
            if last is None:
                continue
            if last in _FAILURE_OUTCOMES:
                return last
            break   # the newest token decides, even when done
    except Exception as exc:
        warn("round_closure_worker_outcome",
             f"{type(exc).__name__}: {exc} — settling as completed")
    return "completed"


def process_event(payload: dict) -> int:
    """Resolve the workspace, append the closure row, run the kernel
    closure faces, rc 0."""
    ws = _resolve_workspace(payload)
    if ws is None:
        return 0
    receipt = _kernel_faces(ws, session_id=str(payload.get("session_id")
                                                   or "")) or {}
    detail = {
        "session_id": payload.get("session_id"),
        "transcript": payload.get("transcript_path"),
        "source": "SubagentStop",
    }
    # the completion row closes the dispatch loop (Face 4 of the
    # progress-coupling card): a WORKER stop carries claim/duration/exit
    # + the attempt binding; a non-worker stop stays silent (the
    # designed posture — only real dispatch completions emit).
    # the closure-row contract: ONE row per SubagentStop —
    # the between-turns wake topology reads it (tracker: the wake face).
    # A WORKER stop's row is
    # ENRICHED with the dispatch-loop binding (claim/duration/exit/
    # attempt); a non-worker stop's row stays plain, exactly as before.
    if receipt:
        detail.update({
            "claim": receipt.get("claim"),
            "attempt_id": receipt.get("attempt_id"),
            "step_id": receipt.get("step_id"),
            "outcome": receipt.get("outcome"),
            "exit": receipt.get("exit"),
        })
    try:
        with scripts_on_path():
            import kunglao_log
            # conditionally-keyed: a plain (non-worker) row keeps its
            # exact pre-change key set — the explicit nulls would be a
            # row-shape drift for the wake-topology consumers
            telemetry = ({"claim": receipt.get("claim"),
                          "duration_ms": receipt.get("duration_ms"),
                          "exit": receipt.get("exit")} if receipt else {})
            kunglao_log.emit_lifecycle(
                ws, CLOSURE_ACTOR, "completed", **telemetry,
                detail=json.dumps(detail, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 — recorder, never blocks
        warn("round_closure", f"{type(exc).__name__}: {exc}")
    return 0


def _kernel_faces(ws: Path, session_id: str = "") -> dict | None:
    """The production round-closure kernel faces (step settlement + closure kernel + RL digest).

    Stop(worker) IS the round-closure event (#429 §6), so this hook now
    hosts what until now fired only from eval_loop_runner:

      - #690 step settlement (FIRST face — settle -> update -> decide):
        the pending step settles here — session tool-call rows aggregate
        into one step-record/2 row (claim_ref via the dispatch-launch
        mapping), the transition closes via
        incremental_reward.append_transition (the production caller),
        and a branch_budget.wall_s overrun lands in attributed-waste.
        Compose below therefore always reads post-settlement state, and
        the dispatch-gate barrier (worker_budget_gates.check_step_settled)
        lifts exactly when this face consumed the stash. No pending step
        = a non-worker subagent stop = nothing written, nothing warned.

      Returns the settle receipt (the additive Face-4 telemetry keys:
      claim/attempt_id/wall_s/outcome/duration_ms/exit) or None — a
      non-worker stop settles nothing.
      - W6: the T2 unblocking-value priority queue builds AND drains
        here (verification_ladder.round_close + drain_t2_queue) — a
        production round consumes its queue head, not just the eval
        loop. NOTE the on-disk queue is written TWICE per closure in
        two ordered shapes: round_close persists the full ``{queue}``
        snapshot, then drain overwrites with ``{dispatched, remaining}``
        — a consumer must tolerate both shapes at that path (the final
        state after a closure is the drained one).
      - W1: the compose single-point composes + versions ONE
        round-strategy object per decision event
        (rlvr.compose.compose + write_strategy; tick = the round axis —
        priority_ratio.round_index, machine-independent, never a wall
        clock). Compose dedups by content_hash, so repeated stops on an
        unchanged workspace re-write nothing — the per-decision-event
        invariant is "per SubagentStop with marker-resolved workspace,
        deduped by content" (#462 recorded scope).
      - Online distillation trigger face: scan the just-completed
        worker's report surface for miss signals (the shelf-miss marker
        in worker status files / an unknown-format probe failure). A
        firing signal emits the production trigger row
        (distill_attempt, phase=triggered — a SIGNAL: the act itself is
        the orchestrator's decision per the loop protocol) and stamps
        runs/distill-trigger.json the orchestrator's tick reads. Budget
        is checked here so the row carries the honest refusal.
      - RL digest face (round-closure visibility): one user-visible line
        per NEW decision (scripts/rl_digest.emit — template + rate limit
        live there), printed as ``{"systemMessage": ...}`` so the
        transcript shows the lead in force + age + last settlement.

    Fail-open double cage: each face is wrapped separately — a kernel
    failure is one rate-limited warn and never disturbs the subagent's
    own stop path."""
    # #690: the step settlement — SubagentStop IS the step boundary, and
    # it runs FIRST so every decision face below sees post-settlement
    # state (settle -> update -> decide). Silent when no step is pending.
    receipt = None
    try:
        with scripts_on_path():
            from rlvr import step_grain
            pending = step_grain.pending_step(ws)
            receipt = step_grain.settle_step(
                ws, session_id, outcome=_worker_outcome(ws, pending))
    except Exception as exc:  # noqa: BLE001 — settle face, never blocks
        warn("round_closure_settle", f"{type(exc).__name__}: {exc}")
    try:
        with scripts_on_path():
            import priority_ratio  # the round axis (machine-independent)
            from rlvr import compose
            obj = compose.compose(ws, tick=priority_ratio.round_index(ws))
            compose.write_strategy(ws, obj)
    except Exception as exc:  # noqa: BLE001 — kernel face, never blocks
        warn("round_closure_compose", f"{type(exc).__name__}: {exc}")
    # The RL digest line — ONE user-visible line per new
    # decision (rate-limited + rendered by scripts/rl_digest.py). It runs
    # AFTER the compose face so it reads the strategy object just versioned
    # (and the one in force when compose is caged); the systemMessage
    # envelope is the Claude Code field rendered in the transcript.
    try:
        with scripts_on_path():
            import rl_digest
            digest_line = rl_digest.emit(ws)
        if digest_line:
            print(json.dumps({"systemMessage": digest_line},
                             ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 — decision face, never blocks
        warn("round_closure_digest", f"{type(exc).__name__}: {exc}")
    try:
        with scripts_on_path():
            import verification_ladder
            verification_ladder.round_close(ws)
            verification_ladder.drain_t2_queue(ws)
    except Exception as exc:  # noqa: BLE001 — kernel face, never blocks
        warn("round_closure_t2", f"{type(exc).__name__}: {exc}")
    try:
        with scripts_on_path():
            import online_distill
            triggers = online_distill.scan_triggers(ws)
            for t in triggers:
                reason = online_distill.refuse_reason(ws, t.token)
                online_distill.emit_trigger_row(
                    ws, t, allowed=(not reason), reason=reason)
            # #487: the stamp carries the problem formulation + the
            # per-facet coverage matrix (fail-open — a formulation
            # failure stamps the pre-#487 shape and warns once)
            formulation = (online_distill.formulate_for_trigger(
                ws, triggers[0]) if triggers else None)
            online_distill.stamp_trigger(ws, triggers,
                                         formulation=formulation)
    except Exception as exc:  # noqa: BLE001 — capability, never blocks
        warn("round_closure_distill", f"{type(exc).__name__}: {exc}")

    return receipt if isinstance(receipt, dict) else None

def main_with_payload(payload: dict) -> int:
    return process_event(payload)


def main(stdin_stream=None) -> int:
    """SubagentStop entry: JSON payload on stdin. FAIL_OPEN on every
    error face — rc 0, silent."""
    try:
        stream = stdin_stream if stdin_stream is not None else sys.stdin
        data = stream.read()
        payload = json.loads(data) if data else {}
    except (json.JSONDecodeError, OSError, ValueError):
        return 0
    try:
        return process_event(payload)
    except Exception:  # noqa: BLE001 — body-level fail-open
        return 0


if __name__ == "__main__":
    sys.exit(main())
