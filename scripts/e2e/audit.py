# -*- coding: utf-8 -*-
"""e2e.audit — the unified E2E audit stream (owner ruling 2026-09-29).

The ruling: 「需要完整补全。另外日志太分散、格式尽量统一」— the E2E trail
used to be scattered across per-checkpoint JSON evidence, ActRecords,
progress.txt decision snapshots, and the workspace kunglao day-file, with
dispatch attempts / method-family choices / strategy compose / posterior
updates / ΔV decisions leaving NO trace at all. This module is the single
writer for the ONE stream that closes those gaps:

    <workspace>/runs/logs/e2e-audit.jsonl

SCHEMA (§6 documentation block)
==============================

Every row is ONE JSON object in the kunglao_log.emit 17-field schema —
THE canonical format (scripts/kunglao_log.py); this stream is a sibling
sink, byte-compatible by construction and pinned so by
tests/test_e2e_runner.py::TestUnifiedAuditTrail:

    ts              ISO8601 UTC timestamp (auto, Z suffix)
    actor           who did it (kunglao_log actor vocabulary; runner-side
                    events are "orchestrator" — the runner IS the runbook
                    orchestrator)
    action          what happened (E2E vocabulary: AUDIT_ACTIONS below)
    claim           claim id the event concerns (or null)
    tool            tool name for tool events (or null)
    artifact        artifact path written or read (or null)
    duration_ms     integer milliseconds (or null)
    exit            integer rc / verdict code (or null)
    detail          free text; structured payloads ride as a JSON-encoded
                    dict (same convention as kunglao_log.emit_lifecycle)
    arm             attribution arm (or null, auto-documented)
    epoch           the tick axis — inherited from the workspace's
                    convergence ledger via kunglao_log (0 = cold start;
                    unreadable ledger = documented null, never
                    fabricated; #472: a garbage numeric input at any
                    emit site = documented "value_unparseable" null —
                    the twin of kunglao_log._safe_int)
    hypothesis_ref  (or null, auto-documented)
    matched_rule    (or null, auto-documented)
    trace_id        mission chain id `tr-<mission>-<seq>` — inherited from
                    the workspace's trace-allocator state; null is documented
                    ("no_trace_allocated") so the un-attributed rate stays
                    measurable
    version         checkout git SHA (auto; unavailable = documented)
    channel         local|ssh|docker|vmr|adb|mcp (KUNGLAO_CHANNEL default)
    null_reasons    {} or {field: why} — a null is NEVER silent

E2E ACTION VOCABULARY (the kunglao_log EMIT_ACTIONS discipline, applied
to this stream — every word below is producer-anchored by
tests/test_e2e_runner.py::TestUnifiedAuditTrail)

    checkpoint_pass / checkpoint_fail / checkpoint_blocked / checkpoint_skip
        One per runtime.record_result call (detail: step, status, rc,
        duration_ms, failed_step). The ORACLE step does NOT use these —
        it emits oracle_verdict (below) so no decision ever gets two rows.
    dispatch_attempt
        Before a dispatch face executes (detail: mode, claim, command,
        cwd, timeout; orchestrator/dry faces log no command — none runs).
    dispatch_result
        After the act (detail: rc, timed_out, duration_ms, stdout_tail,
        stderr_tail; on failure ALSO stderr FULL — diagnosis beats tail
        thrift at the exact moment you need it).
    convergence_decision
        One per decision parse (C6-pre, every loop tick, C7; detail:
        decision, tick, rc) — the progress.txt decision_snapshot face,
        now also in the stream.
    oracle_verdict
        The run's final gold-standard verdict (detail: step, status, rc,
        duration_ms, verdict, min_pair_ratio).
    method_family_recorded / strategy_composed / posterior_updated /
    mainline_decision
        Kernel-facing hooks (§4): they exist, are wired where a surface
        already exists (method_family rides the dispatch envelope), and
        fire only when the kernel activates. Not firing is honest — a
        missing hook would have been the old blind spot again.

GUARANTEE: every decision leaves exactly one event in the stream —
one record_result call = one row; one dispatch_act = one attempt + one
result; one convergence-decision parse = one row; the oracle verdict =
one row (no checkpoint_* twin).

Design contract mirrors kunglao_log: stdlib only; deterministic
serialization (sort_keys + compact separators + ensure_ascii=False);
NEVER raises on write failure — emit degrades to the kunglao_log.warn
fail-open face and returns False (the caller-visible health bit).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import kunglao_log
from harness_common import utc_now_z as _utc_now  # single source (Family F)

#: the stream file (under <ws>/runs/logs/, sibling of the kunglao day files)
AUDIT_FILE = "e2e-audit.jsonl"

#: the controlled vocabulary for this stream (see module docstring)
CHECKPOINT_ACTIONS = frozenset({
    "checkpoint_pass", "checkpoint_fail",
    "checkpoint_blocked", "checkpoint_skip",
})
KERNEL_ACTIONS = frozenset({
    "method_family_recorded", "strategy_composed",
    "posterior_updated", "mainline_decision",
})
AUDIT_ACTIONS = CHECKPOINT_ACTIONS | KERNEL_ACTIONS | frozenset({
    "dispatch_attempt", "dispatch_result",
    "convergence_decision", "oracle_verdict",
})

#: report category buckets (§5) — anything outside them still counts in
#: line_count, it just does not inflate a bucket (garbage stays visible).
CATEGORIES = ("checkpoint", "dispatch", "decision", "oracle", "kernel")


def audit_path(ws) -> Path:
    """<ws>/runs/logs/e2e-audit.jsonl — the unified stream."""
    return Path(ws) / "runs" / "logs" / AUDIT_FILE


def _detail_text(detail) -> str | None:
    """Structured payloads ride as JSON (sort_keys, ensure_ascii=False) —
    the kunglao_log.emit_lifecycle convention, so `detail` stays a str
    field and consumers json.loads when they need structure."""
    if detail is None:
        return None
    if isinstance(detail, str):
        return detail
    try:
        return json.dumps(detail, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        # never-raise contract: a non-serializable payload degrades to a
        # bounded repr marker — logging must never break analysis
        kunglao_log.warn("e2e_audit", f"detail not serializable: {exc}")
        return f"<unserializable {type(detail).__name__}>"


def emit(ws, actor: str, action: str, *, claim: str | None = None,
         tool: str | None = None, artifact: str | None = None,
         duration_ms: int | None = None, exit: int | None = None,
         detail=None, arm: str | None = None,
         null_reasons: dict | None = None) -> bool:
    """Append ONE 17-field event row (kunglao_log.emit schema) to the
    unified stream. Never raises — a write failure degrades to the
    kunglao_log.warn fail-open face and returns False (logging must
    never break analysis).

    Schema fidelity is by construction + by test: the field set mirrors
    kunglao_log.emit exactly (ts/actor/action/claim/tool/artifact/
    duration_ms/exit/detail/arm/epoch/hypothesis_ref/matched_rule/
    trace_id/version/channel/null_reasons), the tick/trace axes are
    inherited from the SAME workspace state files kunglao_log reads,
    and TestUnifiedAuditTrail pins the key set against a real
    kunglao_log row so drift = red."""
    if action not in AUDIT_ACTIONS:
        kunglao_log.warn("e2e_audit", f"unregistered action {action!r} "
                         f"(vocabulary: AUDIT_ACTIONS in e2e/audit.py)")
        return False
    trace_id = kunglao_log.current_trace(ws)
    trace_reason = None if trace_id else "no_trace_allocated"
    # the tick axis, same contract as kunglao_log._resolve_epoch(ws, None):
    # omitted kwarg inherits current_tick; an unreadable ledger is a
    # documented null, never a fabricated value.
    # single-axis inheritance (#255): READ the one tick counter, never
    # keep a local name that pattern-matches a second producer's face
    cur_tick = kunglao_log.current_tick(ws)
    epoch_reason = None if cur_tick is not None else "tick_ledger_unreadable"
    version = kunglao_log._repo_sha()
    reasons: dict = {}
    if null_reasons:
        reasons.update({str(k): str(v) for k, v in null_reasons.items()})
    # #472: the twin numeric cage — same coercion site rule as
    # kunglao_log.emit (at the event dict, after the axis reads), same
    # documented "value_unparseable" null; numeric strings coerce
    # exactly as before.
    safe_duration = kunglao_log._safe_int(duration_ms)
    safe_exit = kunglao_log._safe_int(exit)
    if duration_ms is not None and safe_duration is None:
        reasons["duration_ms"] = "value_unparseable"
    if exit is not None and safe_exit is None:
        reasons["exit"] = "value_unparseable"
    event = {
        "ts": _utc_now(),
        "actor": actor,
        "action": action,
        "claim": str(claim) if claim is not None else None,
        "tool": str(tool) if tool is not None else None,
        "artifact": str(artifact) if artifact is not None else None,
        "duration_ms": safe_duration,
        "exit": safe_exit,
        "detail": _detail_text(detail),
        "arm": str(arm) if arm else None,
        "epoch": int(cur_tick) if cur_tick is not None else None,
        "hypothesis_ref": None,
        "matched_rule": None,
        "trace_id": str(trace_id) if trace_id else None,
        "version": str(version) if version else None,
        "channel": os.environ.get("KUNGLAO_CHANNEL", "local").lower(),
    }
    # the auto-documented null set (kunglao_log.AUTO_NULL_FIELDS) — same
    # honesty rule: a normally-required null is explained in null_reasons
    for f in kunglao_log.AUTO_NULL_FIELDS:
        if event[f] is None and f not in reasons:
            reasons[f] = "omitted"
    if epoch_reason and "epoch" not in reasons:
        reasons["epoch"] = epoch_reason
    if trace_reason and "trace_id" not in reasons:
        reasons["trace_id"] = trace_reason
    if event["version"] is None and "version" not in reasons:
        reasons["version"] = "repo_sha_unavailable"
    # a reason for a field that actually carries a value is stale input
    for f in [k for k in reasons if event.get(k) is not None]:
        del reasons[f]
    event["null_reasons"] = reasons
    line = json.dumps(event, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False) + "\n"
    p = audit_path(ws)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
    except OSError as exc:
        kunglao_log.warn("e2e_audit", f"cannot write {p}: {exc}")
        return False
    return True


# ---------------------------------------------------------------------------
# convenience emitters (thin, vocabulary-anchored wrappers)
# ---------------------------------------------------------------------------

def checkpoint_action(status: str) -> str:
    """status-derived action word: checkpoint_pass/fail/blocked/skip."""
    return f"checkpoint_{str(status).lower()}"


def emit_checkpoint(ws, *, step: str, status: str, rc: int | None,
                    duration_ms: int, failed_step: str | None = None) -> bool:
    """One checkpoint result row (§1/§3 detail contract: step, status,
    rc, duration_ms, failed_step — exactly those keys)."""
    return emit(ws, "orchestrator", checkpoint_action(status),
                detail={"step": step, "status": status, "rc": rc,
                        "duration_ms": duration_ms,
                        "failed_step": failed_step})


def emit_oracle_verdict(ws, *, step: str, status: str, rc: int | None,
                        duration_ms: int, verdict=None,
                        min_pair_ratio=None) -> bool:
    """The ORACLE row — the run's final verdict (exactly one; the ORACLE
    step never also lands a checkpoint_* row)."""
    return emit(ws, "orchestrator", "oracle_verdict",
                detail={"step": step, "status": status, "rc": rc,
                        "duration_ms": duration_ms, "verdict": verdict,
                        "min_pair_ratio": min_pair_ratio})


def emit_dispatch_attempt(ws, claim: str, *, mode: str,
                          command=None, cwd=None, timeout=None,
                          artifact: str | None = None) -> bool:
    """ATTEMPT row — logged BEFORE the act executes. `command` is the
    real argv for auto mode (prompt elided to its file pointer — the
    prompt body lives in the dispatch-prompt evidence file); orchestrator
    and dry faces run no subprocess and log none."""
    return emit(ws, "orchestrator", "dispatch_attempt", claim=claim,
                artifact=artifact,
                detail={"mode": mode, "claim": claim,
                        "command": list(command) if command else None,
                        "cwd": str(cwd) if cwd else None,
                        "timeout": timeout})


def emit_dispatch_result(ws, claim: str, *, mode: str, rc: int | None,
                         timed_out: bool = False, duration_ms: int | None = None,
                         stdout_tail: str = "", stderr_tail: str = "",
                         stderr_full: str | None = None,
                         artifacts=None,
                         exit_null_reason: str = "orchestrator_face_no_subprocess"
                         ) -> bool:
    """RESULT row — logged after the act. On failure the FULL stderr
    rides the detail (§2: diagnosis face; tails stay thrifted).

    #472: a caged act (crashed before/without a subprocess) reports
    rc=None with the CALLER's null reason — the explained-null honesty
    rule, so "no subprocess exit to report" (orchestrator face),
    "the act raised" (wave cage), and "the prompt file was unreadable"
    (auto-face guard) are distinguishable in the stream."""
    if rc is None:
        nulls = {"exit": exit_null_reason}
    else:
        nulls = None
    return emit(ws, "orchestrator", "dispatch_result", claim=claim,
                exit=rc, duration_ms=duration_ms, null_reasons=nulls,
                detail={"mode": mode, "claim": claim,
                        "rc": rc, "timed_out": timed_out,
                        "stdout_tail": stdout_tail,
                        "stderr_tail": stderr_tail,
                        "stderr": stderr_full,
                        "artifacts": [str(a) for a in (artifacts or [])]})


def emit_convergence_decision(ws, decision: str | None, *, tick=None,
                              claim: str | None = None,
                              rc: int | None = None) -> bool:
    """One convergence-decision row per parse (the progress.txt
    decision_snapshot face, now ALSO in the unified stream)."""
    return emit(ws, "orchestrator", "convergence_decision", claim=claim,
                exit=rc,
                detail={"decision": decision, "tick": tick})


def emit_method_family(ws, claim: str, method_family: str, *,
                       envelope: dict | None = None) -> bool:
    """§4 kernel hook: a dispatch envelope carrying method_family."""
    return emit(ws, "orchestrator", "method_family_recorded", claim=claim,
                arm=method_family,
                detail={"method_family": method_family,
                        "envelope": envelope})


def emit_strategy_composed(ws, strategy_ref: str, strategy) -> bool:
    """§4 kernel hook: a strategy compose (pointer + shape, not blobs)."""
    return emit(ws, "orchestrator", "strategy_composed",
                artifact=strategy_ref,
                detail={"strategy_ref": str(strategy_ref),
                        "strategy": strategy})


def emit_posterior_update(ws, cell: str, counts) -> bool:
    """§4 kernel hook: a settlement updating a posterior (cell key + new
    counts)."""
    return emit(ws, "orchestrator", "posterior_updated",
                detail={"cell": str(cell), "counts": counts})


def emit_mainline_decision(ws, claim: str, dv) -> bool:
    """§4 kernel hook: a mainline decision with its ΔV value."""
    return emit(ws, "orchestrator", "mainline_decision", claim=claim,
                detail={"dv": dv})


# ---------------------------------------------------------------------------
# read side: the §5 report summary
# ---------------------------------------------------------------------------

def _category(action: str) -> str | None:
    if action.startswith("checkpoint_"):
        return "checkpoint"
    if action.startswith("dispatch_"):
        return "dispatch"
    if action == "convergence_decision":
        return "decision"
    if action == "oracle_verdict":
        return "oracle"
    if action in KERNEL_ACTIONS:
        return "kernel"
    return None


def read_stats(ws) -> dict:
    """The audit_trail summary for report.json (§5): stream path, parsed
    line count, first/last event ts, per-category counts. Tolerant — a
    missing stream is an all-zero summary, unparseable lines are skipped
    (they never inflate a count, and never crash the report)."""
    stats: dict = {"path": str(audit_path(ws)), "line_count": 0,
                   "first_ts": None, "last_ts": None,
                   "categories": {k: 0 for k in CATEGORIES}}
    try:
        text = audit_path(ws).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return stats
    rows = kunglao_log.iter_jsonl(text.splitlines())
    last: dict | None = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        stats["line_count"] += 1
        last = row
        cat = _category(str(row.get("action")))
        if cat:
            stats["categories"][cat] += 1
        if stats["first_ts"] is None:
            stats["first_ts"] = row.get("ts")
    if last is not None:
        stats["last_ts"] = last.get("ts")
    return stats
