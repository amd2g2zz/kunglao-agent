# -*- coding: utf-8 -*-
"""face_spans - the shared ``face-span/1`` writer for dispatched faces.

The terminal writer (``production_terminal._span``) records only the two
mission-terminal operations. Every RELEASED dispatch face gets its own
start/completed pair here:

    start     -> ``worker_budget_sinks.pre_check``'s ALLOW tail
    completed -> ``round_closure._kernel_faces`` (the SubagentStop close)

Both rows key on the ONE dispatch ledger id - the id the claims txn
writes into the launch stash - so a consumer correlates the pair and
joins it to the dispatch ledger without reversing a hash. The launch
attempt id rides as a dim when known (the attempt that actually closed
the face).

CAGE_FACE + fail-open, like every sibling face: an append failure is one
rate-limited warn and never disturbs the dispatch or the closure. The
span is NEVER closure evidence - only the ledger / terminal checkpoint
certify (the face-span family gotcha). ``usage`` stays ``"unknown"``
(no token accounting in this slice).

Row: schema ``face-span/1``; trace_id = sha256("dispatch:" + id);
span_id = sha256(trace_id + ":" + OPERATION)[:16] - stable across the
pair; event in start | completed | failed; OTel-GenAI vocabulary
(role, gen_ai.operation.name); claim/agent/attempt_id ride only when
known (ADDITIVE_COLUMN).
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

SCHEMA = "face-span/1"
OPERATION = "dispatch"

#: the settle-vocabulary mirror (same set as round_closure's
#: _FAILURE_OUTCOMES - a hooks to scripts import at module level would
#: re-bind by ambient sys.path order, same rule as the hooks twins)
FAIL_OUTCOMES = frozenset({"blocked", "failed", "error"})


def trace_and_span(dispatch_id: str) -> tuple[str, str]:
    """(trace_id, span_id) for one dispatch face - the pair correlation
    key: computed from the dispatch ledger id alone, so the release
    tail and the round closure derive the same ids without shared
    state."""
    trace_id = hashlib.sha256(("dispatch:" + dispatch_id).encode()).hexdigest()
    span_id = hashlib.sha256((trace_id + ":" + OPERATION).encode()).hexdigest()[:16]
    return trace_id, span_id


def stash_dispatch_id(ws, claim: str) -> str | None:
    """The launch stash's dispatch id for one claim (None on any read
    problem, absence or a node that is not a dict - fail-open, the
    stash is consumed by the settle, so callers read it before the
    settle)."""
    try:
        doc = json.loads(
            (Path(ws) / "runs" / f"dispatch-launch-{claim}.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict):
        return None
    did = str(doc.get("dispatch_id") or "").strip()
    return did or None


def _append(ws: Path | str | None, row: dict) -> None:
    """Best-effort append under the face-span/1 schema - one rate-limited
    warn on failure, never a raise (CAGE_FACE)."""
    if not ws:
        return
    try:
        with (Path(ws) / "runs" / "face-spans.jsonl").open("a") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
    except OSError as exc:
        from kunglao_log import warn  # noqa: PLC0415 - the canonical warn

        warn("face_spans.append", f"{type(exc).__name__}: {exc}")


def span_start(
    ws,
    *,
    dispatch_id: str | None,
    claim: str | None,
    agent: str | None,
    attempt_id: str | None = None,
) -> None:
    """The dispatch release tail's start row. Written only when the
    claims txn actually landed this dispatch (the stash's dispatch id
    must match the minted one) - a failed txn never leaves a phantom
    start row."""
    if not dispatch_id or not claim:
        return
    if stash_dispatch_id(ws, claim) != dispatch_id:
        return
    trace_id, span_id = trace_and_span(dispatch_id)
    _append(
        ws,
        {
            "schema": SCHEMA,
            "trace_id": trace_id,
            "span_id": span_id,
            "parent_span_id": None,
            "role": "orchestrator",
            "gen_ai.operation.name": OPERATION,
            "event": "start",
            "time_ns": time.time_ns(),
            "usage": "unknown",
            "dispatch_id": dispatch_id,
            "claim": claim,
            **({"agent": agent} if agent else {}),
            **({"attempt_id": attempt_id} if attempt_id else {}),
        },
    )


def span_end(
    ws,
    *,
    dispatch_id: str | None,
    claim: str | None,
    outcome: str | None,
    agent: str | None = None,
    attempt_id: str | None = None,
) -> None:
    """The round closure's end row: completed for a done worker, failed
    for an outcome in FAIL_OUTCOMES. Dispatch-less closures (legacy
    stashes) write nothing - no id, no row."""
    if not dispatch_id:
        return
    event = "failed" if str(outcome or "").strip() in FAIL_OUTCOMES else "completed"
    trace_id, span_id = trace_and_span(dispatch_id)
    _append(
        ws,
        {
            "schema": SCHEMA,
            "trace_id": trace_id,
            "span_id": span_id,
            "parent_span_id": None,
            "role": "orchestrator",
            "gen_ai.operation.name": OPERATION,
            "event": event,
            "time_ns": time.time_ns(),
            "usage": "unknown",
            "dispatch_id": dispatch_id,
            "claim": claim,
            **({"agent": agent} if agent else {}),
            **({"attempt_id": attempt_id} if attempt_id else {}),
        },
    )
