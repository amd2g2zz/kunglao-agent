# -*- coding: utf-8 -*-
"""signals_stream.py — the append-only outcome-signal stream
(runs/signals.jsonl).

Ruling (2026-09-04): outcome signals are primary; "route signals as text
vs act on them" both converge into the persisted per-round score vector —
but the vector's reward inputs need a STRUCTURED face. Today delivered
facts land only as text annotations: fact-file prose, the facts/_INDEX
row, worker-status lines, claim-register notes (the C-603 shape: a routed
signal became a register annotation). This module is the stream:

  runs/signals.jsonl  — append-only JSONL, one row per outcome signal:

      {"ts": "...Z", "kind": "deliver", "claim": "C-1", ...}

  Kinds wired in the v0.1.6 slice (all producers fail-open — telemetry
  never breaks the producer's path):

    dispatch            — the orchestrator's dispatch ALLOW tail
                          (hooks/dispatch_gate.py main(), after every
                          decision gate passed);
    deliver             — a delivered fact (kunglao_record.record_event on
                          event_type=fact_written; the M4 RECORD path is
                          idempotent so the row is too);
    verify              — an independent verification stamp (record_event on
                          fact_verified);
    confirmed_with_diff — a red-team CONFIRMED verdict carrying DIFF items
                          (line-anchored markers — headings/bullets/item
                          leads — never prose mentions), captured at the
                          terminal rollup (scripts/rollup.py step 1 face)
                          with the substantive-DIFF count riding the row;
                          landed idempotently via signal_id so each verdict
                          file contributes EXACTLY ONE row across all
                          rollups (a substantive DIFF is a negative reward
                          on that round's dispatch action — the v0.2
                          controller applies the penalty, the DATA lands
                          now);
    toss                — DERIVED at read time, never written: a dispatch
                          whose claim never sees a later deliver row
                          (delivery not yet reconciled — the small
                          per-round penalty input).

The Δ-value estimators (action_space.DeltaEstimator) read THIS stream,
never the orchestrator's memory. The per-round factor vector
(mission_ledger) windows the stream by append-order cursor (count_rows)
— machine-independent, no wall clock in the windowing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from harness_common import utc_now_z as _utc_now  # single source
from kunglao_log import iter_jsonl  # noqa: E402  (tolerant reader, single source)

SIGNALS_REL = "runs/signals.jsonl"

KIND_DISPATCH = "dispatch"
KIND_DELIVER = "deliver"
KIND_VERIFY = "verify"
KIND_CONFIRMED_WITH_DIFF = "confirmed_with_diff"

# the four penalty-input kinds of the factor-vector events block
PENALTY_KINDS = (KIND_DISPATCH, KIND_VERIFY, KIND_CONFIRMED_WITH_DIFF)

_WARN_LAST: dict[str, str] = {}


def warn(op: str, reason: str) -> None:
    """Rate-limited stderr WARN (the _zof_warn pattern, issue 276)."""
    if _WARN_LAST.get(op) == reason:
        return
    _WARN_LAST[op] = reason
    print(f"[kunglao-agent] signals_stream WARN (fail-open): "
          f"{op}: {reason}", file=sys.stderr)


def _path(ws) -> Path:
    return Path(ws) / SIGNALS_REL


def append(ws, kind: str, claim: str | None = None, **fields) -> bool:
    """Append one signal row. Append-only via O_APPEND; ts stamped
    (telemetry wall clock — the vector's round axis stays append-order).
    NEVER raises: ANY failure (unserializable field, unwritable path)
    degrades to (False + one rate-limited WARN) so a signal can never
    break the producer's path. Returns True when the row reached the
    stream."""
    try:
        row: dict = {"ts": _utc_now(), "kind": str(kind)}
        if claim is not None:
            row["claim"] = str(claim)
        row.update(fields)
        p = _path(ws)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
        import os
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        return True
    except Exception as exc:  # noqa: BLE001 — a signal never breaks its producer
        warn("append", f"{type(exc).__name__}: {exc}")
        return False


def landed_signal_ids(ws, kind: str | None = None) -> set[str]:
    """The set of signal_ids already in the stream (optionally one kind) —
    the dedup face for append_once (the record_event idiom: the producer
    derives an event identity and lands it once)."""
    out: set[str] = set()
    for row in read(ws):
        sid = row.get("signal_id")
        if isinstance(sid, str) and (kind is None or row.get("kind") == kind):
            out.add(sid)
    return out


def append_once(ws, kind: str, signal_id: str, claim: str | None = None,
                **fields) -> bool:
    """Idempotent append (the record_event idiom applied to the stream):
    the producer derives ``signal_id`` from the UNDERLYING event identity
    (for a verdict file: source name + claim + diff count — an evolving
    verdict with a different count lands again, mirroring outcome_capture's
    evolving-verdict posture); a row carrying the same signal_id is already
    landed, so the append is skipped. Returns True when the row is present
    after the call (appended OR already there), False on write failure.
    NEVER raises (same contract as append)."""
    try:
        if str(signal_id) in landed_signal_ids(ws):
            return True
    except Exception as exc:  # noqa: BLE001 — a dedup read failure appends
        warn("append_once_dedup_scan", f"{type(exc).__name__}: {exc}")
    return append(ws, kind, claim=claim, signal_id=str(signal_id), **fields)


def read(ws) -> list[dict]:
    """Tolerant read (the repo's tolerant-reader posture): dirty/blank
    lines are skipped — a corrupted row is not signal. Missing stream → []."""
    p = _path(ws)
    if not p.exists():
        return []
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [row for row in iter_jsonl(text.splitlines())
            if isinstance(row, dict)]


def count_rows(ws) -> int:
    """Stream length — the per-round window cursor (append order, machine-
    independent; recorded in each factor-vector row as ``signals_rows``)."""
    return len(read(ws))


def penalty_counts(ws, after_rows: int = 0) -> dict[str, int]:
    """The negative-reward penalty inputs over an append-order window:
    counts of dispatch / verify / confirmed_with_diff rows in
    rows[after_rows:], plus toss = dispatch rows in the window whose claim
    has NO later deliver row anywhere in the stream (delivery not yet
    reconciled). Zeros when the stream is absent/empty; never raises."""
    counts = {k: 0 for k in (KIND_DISPATCH, KIND_VERIFY,
                             KIND_CONFIRMED_WITH_DIFF)}
    counts["toss"] = 0
    try:
        all_rows = read(ws)
        window = all_rows[max(0, int(after_rows)):]
        for i, row in enumerate(window):
            kind = str(row.get("kind") or "")
            if kind in counts:
                counts[kind] += 1
            elif kind == "toss":
                continue  # toss is derived, never written
            if kind == KIND_DISPATCH:
                claim = row.get("claim")
                later_deliver = any(
                    x.get("kind") == KIND_DELIVER and x.get("claim") == claim
                    for x in all_rows[after_rows + i + 1:])
                if not later_deliver:
                    counts["toss"] += 1
        return counts
    except Exception as exc:  # noqa: BLE001 — a read failure is zero signal
        warn("penalty_counts", f"{type(exc).__name__}: {exc}")
        return counts
