# -*- coding: utf-8 -*-
"""scheduler_events.py — the scheduler's event-driven wake stream
(runs/scheduler/events.jsonl).

The loop's wake mechanism was pure time polling: a fixed cron woke the
session whether or not anything happened. THIS module is the event
spine of the replacement — one append-only JSONL stream of the
scheduler's MATERIAL events, written by the faces that already record
the underlying facts (one append each, fail-open, derived from data the
producer has in hand — never a second IO pass), read by the non-LLM
watcher (scheduler_watch.py) and drained by the session's scheduler
drain face (loop_scheduler --drain-events).

The events are EPHEMERAL WAKE SIGNALS, not learning rows: every kind
has a durable ledger home already (the gate reject rides the unified
experience ledger's dispatch-reject rows, the deadline rides the
telemetry timer rows and its stop record, the settlement rides the
settlement family), so this stream carries NO consolidated-ledger row
and registers nothing in NATIVE_SCHEMAS — a duplicated telemetry row
that no reward face reads would be pure IO waste. The durable rows
remain the truth; this stream is the wake channel. Rows still carry a
self-describing ``scheduler-event/1`` schema stamp (protocol, not a
ledger registration).

Closed vocabulary — every kind maps EXPLICITLY onto a BUS A wake
class (mechanism_scheduler.EVENT_CLASSES, the only vocabulary
wake_verdict wakes on — #1086 S19 unified the two buses' semantics);
the mapping IS the vocabulary and the materiality semantics:

    gate-reject       -> stall        the dispatch gate hard-rejected a
                                     dispatch (the round's attempted
                                     progress is blocked)
    deadline-fired    -> stall        a rollout's learned deadline fired
                                     (that rollout stalled)
    settle-completed  -> settlement   a step/round settlement closed
                                     (claim_settled's family)

worker-exit and verdict-landed LEFT the vocabulary (#1086): neither
had a producer anywhere — the event closure covers three facts, not
five — and their durable wake already rides the ledger's claim_settled
settlement rows (BUS A's settlement class), so keeping the words would
have declared a coverage that never existed.

Heartbeats and ticks NEVER enter the file: ``append`` REFUSES a kind
outside the mapping (one warn + False — the writer-side gate), and
``material_rows`` drops any row whose kind is unmapped (the reader-side
gate, byte-tolerant against hand-edited files — including legacy rows
of the removed kinds). Materiality is DERIVED from the mapping, never
declared by a static set: the gate's semantic half is the mapped wake
class, its state half is the consumer's cursor (the watcher's byte
cursor, the drain's row cursor) — an already-consumed row is not
material to that consumer. The materiality gate runs BEFORE any LLM
turn: the watcher and the drain are both mechanical.

House pattern: the outcome-signal stream (signals_stream.py) —
append-only via one O_APPEND write, tolerant reads (a corrupted row is
not signal), and the canonical fail-open warn (a signal never breaks
its producer's path).
"""
from __future__ import annotations

import json
from pathlib import Path

from harness_common import utc_now_z as _utc_now  # single source
from kunglao_log import iter_jsonl, warn  # noqa: E402  (tolerant reader)

#: the stream's rel (under runs/scheduler/ — a SIBLING concept of the
#: per-rollout wake map, not a replacement for it)
EVENTS_REL = Path("runs") / "scheduler" / "events.jsonl"

#: the self-describing row stamp (protocol; NOT a NATIVE_SCHEMAS entry —
#: the rows never enter a consolidated file)
SCHEMA = "scheduler-event/1"

KIND_GATE_REJECT = "gate-reject"
KIND_DEADLINE_FIRED = "deadline-fired"
KIND_SETTLE_COMPLETED = "settle-completed"

#: kind -> BUS A wake class — THE worth-waking semantics (#1086 S19).
#: The values are mechanism_scheduler.EVENT_CLASSES members (the
#: vocabulary ``wake_verdict`` wakes on via the tick's events_seen);
#: pinned against it in tests/test_scheduler_events_1001.py rather
#: than imported, so the watcher process keeps its light import
#: surface (the no-model AST wall's allowlist).
KIND_WAKE_CLASS = {
    KIND_GATE_REJECT: "stall",          # the refused dispatch blocks the round
    KIND_DEADLINE_FIRED: "stall",       # the fired deadline IS that rollout's stall
    KIND_SETTLE_COMPLETED: "settlement",  # the round closed — claim_settled's family
}

#: the closed event vocabulary — the mapping's key set, DERIVED (there
#: is no parallel kind list and no static material set beside the
#: mapping)
KINDS = tuple(KIND_WAKE_CLASS)


def wake_class(kind) -> str | None:
    """The kind's BUS A wake class — the only worth-waking semantics.
    None for a kind outside the mapping (noise, or a removed legacy
    kind)."""
    return KIND_WAKE_CLASS.get(str(kind or ""))


def is_material(kind) -> bool:
    """The closed-vocabulary check — the reader-side half of the
    materiality gate: a row is material iff its kind MAPS to a wake
    class. The semantics live in the mapping (never a static
    frozenset of "material by definition" kinds); the gate's state
    half is the consumer's cursor — an already-drained row is not
    material to that consumer."""
    return wake_class(kind) is not None


def _path(ws) -> Path:
    return Path(ws) / EVENTS_REL


def state_path(ws, name: str) -> Path:
    """One runs/scheduler/<name> state file (the watcher's byte cursor,
    the drain's row cursor — siblings of the stream, never inside it)."""
    return Path(ws) / "runs" / "scheduler" / name


def append(ws, kind: str, claim: str | None = None, **fields) -> bool:
    """Append one event row. THE WRITER-SIDE MATERIALITY GATE: a kind
    that maps to no wake class is refused (one warn + False — a
    heartbeat, a tick, or a removed legacy kind can never wake the
    session). Append-only via a
    single O_APPEND write; ts stamped. NEVER raises: any failure
    degrades to (False + one RATE-LIMITED warn) so a wake signal can
    never break the producer's path — the warn rides the house
    once-per-workspace-state face (warn_once_stateful, pinned to THIS
    workspace for the call and restored after), so a persistent
    blocker (an unwritable stream) warns once per reason, never once
    per producer invocation. Returns True when the row reached the
    stream."""
    kind_token = str(kind or "").strip()
    if wake_class(kind_token) is None:
        warn("scheduler_events.append",
             f"unmapped kind {kind!r} refused — a wake row must map to "
             f"a BUS A wake class "
             f"({', '.join(f'{k}->{c}' for k, c in KIND_WAKE_CLASS.items())})")
        return False
    try:
        row: dict = {"ts": _utc_now(), "schema": SCHEMA,
                     "kind": kind_token}
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
        _warn_failure(ws, f"{type(exc).__name__}: {exc}")
        return False


def _warn_failure(ws, reason: str) -> None:
    """The append failure's rate-limited warn: once per (workspace,
    reason) until the reason changes — a reject-heavy session with a
    persistently broken stream must not warn-storm. The workspace pin
    is scoped to THIS call (saved/restored) so the library face never
    leaves the process's diagnostics resolution changed as a side
    effect."""
    from kunglao_log import set_warn_workspace, warn_once_stateful, \
        warn_workspace
    prior = warn_workspace()
    set_warn_workspace(ws)
    try:
        warn_once_stateful("scheduler_events.append", reason,
                           state_key=reason)
    except Exception:  # noqa: BLE001 — visibility is best-effort
        warn("scheduler_events.append", reason)
    finally:
        set_warn_workspace(prior)


def read(ws) -> list[dict]:
    """Tolerant read (the repo's tolerant-reader posture): dirty/blank
    lines are skipped — a corrupted row is not signal. Missing stream
    -> []."""
    p = _path(ws)
    if not p.exists():
        return []
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [row for row in iter_jsonl(text.splitlines())
            if isinstance(row, dict)]


def material_rows(ws) -> list[dict]:
    """The MATERIAL rows in append order — ``read`` plus the reader-side
    closed-vocabulary gate (rows whose kind maps to no wake class are
    dropped, not woken on)."""
    return [row for row in read(ws) if is_material(row.get("kind"))]


def count_rows(ws) -> int:
    """Stream length (append order) — the drain face's machine-
    independent cursor basis."""
    return len(read(ws))
