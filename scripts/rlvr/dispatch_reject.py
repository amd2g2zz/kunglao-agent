# -*- coding: utf-8 -*-
"""rlvr/dispatch_reject.py — the dispatch-gate reject, recorded and fed back.

The dispatch seam's REJECT face (issue-1005, S8): a dispatch the gate
hard-rejects (rc=2, any reason family — structural, plan-first, budget,
admission) is no longer silent. The gate's single reject tail appends
one ``dispatch-reject/1`` row into the unified experience ledger
(``consolidated_ledger.append(ws, "experience", row)``) carrying the
house transition-row vocabulary: ``claim_ref`` / ``dispatch_id``
attribution, ``action_type: "dispatch"``, ``o.status: "rejected"`` with
the gate reason in ``o.class``, and the identity ``ts``. The row shape
is identical for every reject reason — ONE seam, not per-reason copies;
only ``o.class`` / ``detail`` carry the reason face.

The consumer side is the decision machine's feedback face:
``feedback_face(ws)`` is a pure read over the experience family (plus
the register's live-claim set and the dispatch declaration rows as the
allow-evidence face) that groups the rows per claim + reason and
classifies each claim against ``REJECT_RETRY_MAX``:

  - ``active``  — live claims with 1..MAX-1 same-reason rejects whose
    last reject is newer than the claim's last ALLOWED dispatch (the
    declaration row): the loop is still bouncing off the gate;
  - ``exhausted`` — live claims at MAX same-reason rejects: the loop
    cannot act on this claim, the decision must go terminal.

Non-retryable reason classes (irreversible-action refusals) land rows
for the audit but never count — a refusal is not a retry failure. The
counting face reads the workspace's COMPLETE dispatch-reject row set
(schema-filtered: bounded by this workspace's own hard-reject history,
not by the shared multi-schema file), so a burst of newer rows can
never window an at-max claim out of its evidence; the window bounds
only the declaration-row recovery read (whose latest-row face is
window-stable by construction).

A claim that left the live register (settled / terminal / suspended) or
whose dispatch pipeline flowed again after its last reject (an allow
newer than the reject) goes quiet — history never parks a recovered
loop. The terminal decision's word is DERIVED from the disposition
algebra's route-ledger gate (consumed, never extended) and degrades to
a documented sentinel instead of crashing on a vocabulary refactor.

Fail-open everywhere: reads tolerate absent/dirty files ([]), the face
degrades to the empty face on layer errors with one loud warn, and a
failed append is reported (``appended`` False), never hidden and never
raised into the gate.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from kunglao_log import warn

from . import consolidated_ledger
from . import strategic_action

#: the row's schema stamp (the unified-ledger attribution contract)
SCHEMA = "dispatch-reject/1"

#: the bounded retry policy: repeated hard rejects of the SAME claim for
#: the SAME reason past this count mean the dispatch path cannot act —
#: the decision goes terminal (the disposition word below). A policy
#: constant, not a fitted parameter (state.py precedent).
REJECT_RETRY_MAX = 3

#: how many RECENT declaration rows the recovery face considers for the
#: allow evidence (the declaration reader's window; the LAST row is
#: always inside it, so the latest-allow face is window-stable)
REJECT_HISTORY_MAX = 200

#: the claim token for a hard reject whose payload never parsed to a
#: claim id (an unparsed dispatch the lane/structural faces still
#: refused): the row lands for the audit with this marker, and the
#: feedback face naturally scopes it out (the marker is never a live
#: register claim)
UNPARSED_CLAIM = "(unparsed-dispatch)"

#: reason classes a retry counter must NEVER count: an irreversible-
#: action refusal is not a retryable dispatch failure (re-issuing it is
#: forbidden, not failing) — the row lands for the audit, the face
#: excludes it from the active/exhausted classification
NON_RETRYABLE_REASONS = ("must_stop",)

#: the documented terminal word — the FALLBACK the derivation below
#: degrades to (with one warn) when the algebra's gate table ever drops
#: the route-ledger face; a module import must never crash on a
#: vocabulary refactor (the decision machine imports this module)
EXHAUSTED_SENTINEL = "ATTEMPTED_EXHAUSTED"

#: every field the `dispatch-reject/1` row carries (fixed set, nullable
#: when absent — the declaration row's shape-stability posture)
ROW_FIELDS = ("schema", "ts", "claim_ref", "dispatch_id", "action_type",
              "o", "detail", "trace_id")

#: the reason text bound (mirrors the sidecar row's msg clamp)
_REASON_MAX = 200
_DETAIL_MAX = 500

#: the identity timestamp format (the house ISO-8601 UTC stamp)
_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class DispatchRejectError(ValueError):
    """A row violates the `dispatch-reject/1` contract."""


def _derive_exhausted_word() -> str:
    """The terminal disposition word, derived from the algebra's own
    vocabulary + gate table (imported, never restated or extended).
    Degrades to the documented sentinel — with one warn — when the
    route-ledger gate is gone AND when the derivation resolves to any
    OTHER word (a vocabulary refactor assigning the gate to a different
    disposition must never silently rename the terminal decision). Never
    raises at import."""
    try:
        from . import disposition as _disp  # noqa: PLC0415 — lazy (cycle)
        word = next(
            w for w in _disp.DISPOSITIONS
            if "route_ledger" in _disp.GATE_FOR_DISPOSITION.get(w, ()))
        if word != EXHAUSTED_SENTINEL:
            warn("rlvr.dispatch_reject",
                 f"disposition algebra's route-ledger gate resolved to "
                 f"{word!r}, not the documented terminal word — degraded "
                 f"to the sentinel (the vocabulary drifted)")
            return EXHAUSTED_SENTINEL
        return word
    except StopIteration:
        warn("rlvr.dispatch_reject",
             "disposition algebra carries no route-ledger gate — terminal "
             "word degraded to the documented sentinel")
        return EXHAUSTED_SENTINEL
    except Exception as exc:  # noqa: BLE001 — degrade, never crash import
        warn("rlvr.dispatch_reject",
             f"disposition algebra unreadable ({type(exc).__name__}: {exc}) "
             f"— terminal word degraded to the documented sentinel")
        return EXHAUSTED_SENTINEL


#: the terminal decision word (the disposition vocabulary's own)
EXHAUSTED_DISPOSITION = _derive_exhausted_word()


def _nonempty_str(value) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.strip()
    return token or None


def _validate_ts(ts) -> None:
    """The shared identity-timestamp check (calendar-validated)."""
    if not isinstance(ts, str):
        raise DispatchRejectError(
            "ts must be an ISO-8601 UTC second stamp (YYYY-MM-DDTHH:MM:SSZ)")
    try:
        datetime.strptime(ts, _TS_FORMAT)
    except ValueError as exc:
        raise DispatchRejectError(
            "ts must be an ISO-8601 UTC second stamp (YYYY-MM-DDTHH:MM:SSZ)"
        ) from exc


def build_reject_row(*, claim: str, reason: str, detail=None,
                     trace_id=None, ts: str) -> dict:
    """Validate and shape one `dispatch-reject/1` row (pure).

    ``reason`` is the gate face identity (the count key — same claim +
    same reason group together); ``detail`` is the human-readable
    message tail (optional); ``trace_id`` is the mission chain id when
    the dispatch resolved one (optional). The row mirrors the house
    transition-row attribution columns (``claim_ref`` / ``dispatch_id``
    / ``action_type``) and outcome face (``o.status`` / ``o.class``).
    """
    claim_token = _nonempty_str(claim)
    if claim_token is None:
        raise DispatchRejectError("claim must be a non-empty string")
    reason_token = _nonempty_str(reason)
    if reason_token is None:
        raise DispatchRejectError("reason must be a non-empty string")
    if len(reason_token) > _REASON_MAX:
        raise DispatchRejectError(
            f"reason must be at most {_REASON_MAX} characters")
    detail_token = _nonempty_str(detail)
    if detail_token is not None and len(detail_token) > _DETAIL_MAX:
        detail_token = detail_token[:_DETAIL_MAX]
    if trace_id is not None and _nonempty_str(trace_id) is None:
        raise DispatchRejectError(
            "trace_id must be a non-empty string or None")
    _validate_ts(ts)
    return {
        "schema": SCHEMA,
        "ts": ts,
        "claim_ref": claim_token,
        "dispatch_id": claim_token,
        "action_type": "dispatch",
        "o": {"status": "rejected", "class": reason_token},
        "detail": detail_token,
        "trace_id": _nonempty_str(trace_id),
    }


def append_reject(ws, row: dict) -> dict:
    """Append one dispatch-reject row through the unified ledger.

    APPEND-only by contract: repeated rejects of the same claim are the
    retry history the face counts, so there is no dedupe and no
    idempotence. The row is revalidated through the builder, so the file
    only ever carries builder-shaped rows. A failed append is reported
    (``appended`` False), never hidden — a reject with no ledger row
    stays invisible to the decision face.
    """
    if not isinstance(row, dict) or row.get("schema") != SCHEMA:
        raise DispatchRejectError(f"row must be a {SCHEMA!r} object")
    missing = [field for field in ROW_FIELDS if field not in row]
    if missing:
        raise DispatchRejectError(
            f"row missing required field(s): {missing}")
    o = row.get("o")
    canonical = build_reject_row(
        claim=row.get("claim_ref"), reason=(o or {}).get("class"),
        detail=row.get("detail"), trace_id=row.get("trace_id"),
        ts=row.get("ts"))
    appended = bool(consolidated_ledger.append(ws, "experience", canonical))
    return {"row": canonical, "appended": appended}


def reject_rows(ws, history_max: int = REJECT_HISTORY_MAX) -> list[dict]:
    """The RECENT dispatch-reject rows, oldest first (at most the last
    ``history_max`` rows; absent/dirty file reads [])."""
    rows = consolidated_ledger.read(ws, "experience", schema_prefix=SCHEMA)
    if history_max is not None and history_max >= 0:
        rows = rows[-history_max:]
    return rows


def _live_claim_ids(ws) -> set[str]:
    """The register's live claims (non-terminal, non-suspended) — the
    scoping set that keeps settled history from firing the feedback.
    Fail-open: an unreadable/absent register scopes everything out (the
    face goes quiet; a broken register is the register gates' face, not
    ours)."""
    live: set[str] = set()
    try:
        import yaml  # noqa: PLC0415 — lazy (the read face only)
        from retract_claim import RETRACTED, TERMINAL_WITH_RETRACTED  # noqa: PLC0415
        from status_defs import SUSPENDED  # noqa: PLC0415
        reg = (yaml.safe_load(
            (Path(ws) / "claim-register.yaml")
            .read_text(encoding="utf-8")) or {}).get("claims") or []
        for c in reg:
            cid = _nonempty_str((c or {}).get("id"))
            status = str((c or {}).get("status") or "").upper()
            if cid and status not in TERMINAL_WITH_RETRACTED \
                    and status not in SUSPENDED:
                live.add(cid)
        _ = RETRACTED  # the terminal set's sibling import face
    except Exception as exc:  # noqa: BLE001 — fail-open, loud
        warn("rlvr.dispatch_reject.live_ids",
             f"{type(exc).__name__}: {exc} — live-claim scoping empty")
    return live


def _allow_ts_by_claim(ws, history_max: int = REJECT_HISTORY_MAX
                       ) -> dict[str, str]:
    """The last ALLOWED-dispatch ts per claim (the declaration rows are
    the allow evidence — the ALLOW tail writes one per passing
    dispatch). Claims with no declaration face never recover here."""
    allow: dict[str, str] = {}
    for row in strategic_action.declaration_rows(ws, history_max):
        claim = _nonempty_str(row.get("claim"))
        ts = _nonempty_str(row.get("ts"))
        if claim and ts and ts > allow.get(claim, ""):
            allow[claim] = ts
    return allow


def _same_reason_counts(rows: list) -> dict[tuple[str, str], dict]:
    """Retryable per-(claim, reason) counts with the last ts (pure).

    Non-dict rows and non-retryable reason classes are skipped — a
    refusal is not a retry failure."""
    counts: dict[tuple[str, str], dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        claim = _nonempty_str(row.get("claim_ref"))
        o = row.get("o")
        reason = _nonempty_str((o or {}).get("class")
                               if isinstance(o, dict) else None)
        ts = _nonempty_str(row.get("ts")) or ""
        if not claim or not reason:
            continue
        if reason in NON_RETRYABLE_REASONS:
            continue
        slot = counts.setdefault(
            (claim, reason), {"count": 0, "last_ts": ""})
        slot["count"] += 1
        if ts > slot["last_ts"]:
            slot["last_ts"] = ts
    return counts


def _top_reason_by_claim(counts: dict[tuple[str, str], dict]) -> dict:
    """Per claim: the max-count reason wins; ties resolve to the latest
    ts (pure)."""
    top: dict[str, dict] = {}
    for (claim, reason), slot in counts.items():
        cur = top.get(claim)
        candidate = {"count": slot["count"], "reason": reason,
                     "last_ts": slot["last_ts"]}
        if cur is None or slot["count"] > cur["count"] or (
                slot["count"] == cur["count"]
                and slot["last_ts"] > cur["last_ts"]):
            top[claim] = candidate
    return top


def feedback_face(ws, history_max: int = REJECT_HISTORY_MAX) -> dict:
    """The decision machine's reject feedback face (pure read).

    Returns ``{"rows", "by_claim", "active", "exhausted", "retry_max"}``:

      - ``rows`` — the workspace's complete dispatch-reject row count;
      - ``by_claim`` — per claim: the top same-reason count (the
        max-count reason wins; ties resolve to the latest ts), that
        reason, and the claim's last reject ts;
      - ``active`` / ``exhausted`` — the live claims still bouncing off
        the gate (sub-max / at-max, respectively), each fresh (last
        reject newer than the claim's last allowed dispatch);
      - ``retry_max`` — the bounded-retry policy constant (single
        source with the consumer's pin).

    The counts run over the COMPLETE dispatch-reject row set
    (``history_max`` bounds only the declaration-row recovery read):
    the evidence set is schema-filtered — bounded by this workspace's
    own hard-reject history, never by the shared multi-schema file —
    so a burst of newer rows can never window an at-max claim out of
    its exhaustion evidence. Non-retryable reason classes are excluded
    from the counts (a refusal is not a retry failure). Fail-open: any
    layer error degrades to the EMPTY face with one warn — a broken
    ledger must never sink the decision machine.
    """
    face = {"rows": 0, "by_claim": {}, "active": [], "exhausted": [],
            "retry_max": REJECT_RETRY_MAX}
    try:
        rows = reject_rows(ws, history_max=None)
        face["rows"] = len(rows)
        face["by_claim"] = _top_reason_by_claim(
            _same_reason_counts(rows))
        live = _live_claim_ids(ws)
        allow = _allow_ts_by_claim(ws, history_max)
        for claim, slot in face["by_claim"].items():
            if claim not in live:
                continue  # settled/suspended history — the face goes quiet
            if slot["last_ts"] <= allow.get(claim, ""):
                continue  # an allowed dispatch flowed after the reject
            if slot["count"] >= REJECT_RETRY_MAX:
                face["exhausted"].append(claim)
            else:
                face["active"].append(claim)
        face["active"].sort()
        face["exhausted"].sort()
    except Exception as exc:  # noqa: BLE001 — the empty face, loudly
        warn("rlvr.dispatch_reject.feedback_face",
             f"{type(exc).__name__}: {exc} — reject feedback degraded to "
             f"the empty face")
        face = {"rows": 0, "by_claim": {}, "active": [], "exhausted": [],
                "retry_max": REJECT_RETRY_MAX}
    return face
