# -*- coding: utf-8 -*-
"""settlement/draft_commit.py — the two-phase landing faces (#884).

Drafts land at DISPATCH end (staging); the COMMIT lands at ROLLOUT end
(ONE ``settlement-commit/1`` marker naming the draft batch). A
rolled-back rollout IS committed — its marker prices the NEGATIVE
terminal adjustment (the whole-trajectory clawback is the settlement,
never an omission); what a rollback excludes is the TERMINAL BONUS.
An explicit ``discard_drafts`` face additionally lands a
``settlement-discard/1`` marker so the loop's rollback DECISION is
audited, and a commit after a discard is refused (a rollback already
ruled the batch dead — credit
must never resurrect). The append-only ledger never rewrites drafts:
committing stamps, it does not move rows.

Crash resilience: a draft is RE-COMPUTABLE from the trajectory ledger
(the (s,a,r) source of truth — ``per_dispatch.dispatch_spend`` replays
the result rows) and ``ensure_draft`` is the re-derivation entry: a
re-draft of the same (rollout_id, dispatch identity) is REFUSED with
``already-drafted`` (the prober's already-landed guard — the append is
not atomic, so a crash mid-landing followed by a blind retry must never
double-bank credit). A draft arriving after its batch's marker is
refused too (``batch-already-committed``): the read-time JOIN is by
batch_id, so a late draft would otherwise retroactively inflate a
certified aggregate.

Fail-closed vs receipt: structural garbage RAISES (the loop-internal
posture); identity collisions (re-draft, double commit) are EXPECTED
crash-recovery paths and return an ``appended: False`` receipt, never a
silent drop. Reads of the committed view additionally fail-closed on
stream tampering (a draft after the marker, a foreign batch_id) — a
silently tolerated tampered stream would fabricate the aggregate.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any, Mapping

from settlement import per_dispatch, rollout_agg  # noqa: E402 — path set below
from settlement.per_dispatch import DRAFT_SCHEMA  # noqa: E402

_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
for _p in (Path(__file__).resolve().parents[1], _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from rlvr import consolidated_ledger as _cl  # noqa: E402
from rlvr import q_cells  # noqa: E402

#: the marker schema stamps (the receipt-stamp discipline).
COMMIT_SCHEMA = "settlement-commit/1"
DISCARD_SCHEMA = "settlement-discard/1"

#: the read face only ever keeps the three settlement stamps — the
#: family file hosts other faces' rows too (settlement-wire/1, the
#: distill rows), and a foreign stamp is not ours to validate.
_READ_PREFIXES = ("settlement-draft", "settlement-commit",
                  "settlement-discard")

#: the trajectory action kinds that CLOSE a rollout, mapped onto the
#: credit/returns TERMINALS vocabulary (last matching action wins).
_TERMINAL_FROM_ACTION = {
    "terminate_rollout": "completed",
    "rollback": "rolled_back",
}


def _fail(field: str, why: str) -> ValueError:
    return ValueError(f"settlement.draft_commit.{field}: {why}")


def _now() -> str:
    from harness_common import utc_now_z  # noqa: PLC0415 — the q_cells mirror
    return utc_now_z()


def _non_empty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail(field, "must be a non-empty string")
    return value


def _checked_draft(priced: Any) -> dict:
    """The priced-row wall (fail-closed): the exact draft shape, a
    finite non-negative spend, a finite credit, and the recomputed
    batch_id — a mismatched batch_id would strand the draft outside
    its own commit marker's JOIN forever, so it never lands."""
    if not isinstance(priced, Mapping) \
            or priced.get("schema") != DRAFT_SCHEMA:
        raise _fail("priced",
                    f"must be a {DRAFT_SCHEMA!r} mapping")
    rid = _non_empty(priced.get("rollout_id"), "priced.rollout_id")
    _non_empty(priced.get("dispatch_id"), "priced.dispatch_id")
    _non_empty(priced.get("batch_id"), "priced.batch_id")
    spend = priced.get("spend")
    if isinstance(spend, bool) or not isinstance(spend, (int, float)) \
            or not math.isfinite(spend) or spend < 0.0:
        raise _fail("priced.spend", "must be a finite number >= 0")
    credit = priced.get("credit")
    if isinstance(credit, bool) or not isinstance(credit, (int, float)) \
            or not math.isfinite(credit):
        raise _fail("priced.credit", "must be a finite number")
    verdicts = priced.get("verdicts")
    if not isinstance(verdicts, Mapping):
        raise _fail("priced.verdicts", "must be the verdict mapping")
    if set(verdicts) != set(per_dispatch.VERDICT_LAYERS) \
            or not all(isinstance(verdicts[k], bool)
                       for k in per_dispatch.VERDICT_LAYERS):
        raise _fail("priced.verdicts",
                    f"must carry exactly {sorted(per_dispatch.VERDICT_LAYERS)}"
                    f" as bools")
    expected = per_dispatch.batch_id(rid)
    if priced.get("batch_id") != expected:
        raise _fail("priced.batch_id",
                    f"{priced.get('batch_id')!r} does not match the "
                    f"rollout's batch identity {expected!r}")
    return dict(priced)


def _rows(ws) -> list[dict]:
    """The three settlement stamps of the family file, append order —
    the ONLY rows these faces own."""
    return _cl.read(ws, "settlement", schema_prefix=_READ_PREFIXES)


def _draft_rows(ws) -> list[dict]:
    return [r for r in _rows(ws) if r.get("schema") == DRAFT_SCHEMA]


def _marker_rows(ws, schema: str) -> list[dict]:
    return [r for r in _rows(ws) if r.get("schema") == schema]


def draft_rows(ws, rollout_id: str) -> list[dict]:
    """One rollout's draft rows, append order — the batch's staging
    content (and the crash-recovery re-scan's input)."""
    rid = _non_empty(rollout_id, "rollout_id")
    return [r for r in _draft_rows(ws)
            if str(r.get("rollout_id") or "") == rid]


def land_draft(ws, priced: Mapping, *, ts: str | None = None) -> dict:
    """Land ONE priced draft row into the settlement family. Idempotent
    on (rollout_id, dispatch_id) — ``already-drafted``; refused after
    the batch's commit marker — ``batch-already-committed``; refused
    after a discard marker — ``batch-discarded`` (staging into a dead
    batch would pollute the audit the discard sealed). Structural
    garbage raises (see _checked_draft). ``ts`` rides the caller's
    receipt only through the row itself; the faces add nothing."""
    row = _checked_draft(priced)
    if ts is not None:
        _non_empty(ts, "ts")
        row = dict(row, ts=ts)
    rid = row["rollout_id"]
    did = row["dispatch_id"]
    for existing in _draft_rows(ws):
        same = (str(existing.get("rollout_id") or "") == rid
                and str(existing.get("dispatch_id") or "") == did)
        if same:
            return {"schema": DRAFT_SCHEMA, "appended": False,
                    "reason": "already-drafted",
                    "batch_id": row["batch_id"],
                    "rollout_id": rid, "dispatch_id": did}
    commits = _marker_rows(ws, COMMIT_SCHEMA)
    if any(str(m.get("batch_id") or "") == row["batch_id"]
           for m in commits):
        return {"schema": DRAFT_SCHEMA, "appended": False,
                "reason": "batch-already-committed",
                "batch_id": row["batch_id"],
                "rollout_id": rid, "dispatch_id": did}
    if any(str(m.get("batch_id") or "") == row["batch_id"]
           for m in _marker_rows(ws, DISCARD_SCHEMA)):
        return {"schema": DRAFT_SCHEMA, "appended": False,
                "reason": "batch-discarded",
                "batch_id": row["batch_id"],
                "rollout_id": rid, "dispatch_id": did}
    appended = _cl.append(ws, "settlement", row)
    return {"schema": DRAFT_SCHEMA, "appended": appended,
            "reason": None if appended else "append-refused",
            "batch_id": row["batch_id"],
            "rollout_id": rid, "dispatch_id": did}


def ensure_draft(ws, rollout_id: str, dispatch_id: str, spend: Any,
                 verdicts: Mapping[str, bool], *,
                 ts: str | None = None) -> dict:
    """Price + land in one call — the loop's dispatch-end entry AND the
    crash-recovery entry (a re-run re-prices deterministically from the
    trajectory and converges to ``already-drafted``, never a second
    row)."""
    priced = per_dispatch.price_dispatch(rollout_id, dispatch_id, spend,
                                         verdicts, ts=ts)
    return land_draft(ws, priced)


def commit_batch(ws, rollout_id: str, *, ts: str | None = None) -> dict:
    """Land the ONE commit marker naming the rollout's draft batch:
    ``{schema, ts, batch_id, rollout_id, total_credit}`` where
    total_credit = Σ(draft credits) — the marker certifies the batch's
    own content; the terminal adjustment joins only at aggregate read
    time (rollout_agg). Refusals: ``already-committed``, ``no-drafts``,
    ``batch-discarded`` (a rollback ruled the batch dead)."""
    rid = _non_empty(rollout_id, "rollout_id")
    batch = per_dispatch.batch_id(rid)
    drafts = draft_rows(ws, rid)
    if not drafts:
        return {"schema": COMMIT_SCHEMA, "appended": False,
                "reason": "no-drafts", "batch_id": batch,
                "rollout_id": rid, "total_credit": 0.0,
                "dispatch_count": 0}
    if any(str(m.get("batch_id") or "") == batch
           for m in _marker_rows(ws, COMMIT_SCHEMA)):
        return {"schema": COMMIT_SCHEMA, "appended": False,
                "reason": "already-committed", "batch_id": batch,
                "rollout_id": rid, "total_credit": 0.0,
                "dispatch_count": len(drafts)}
    discards = _marker_rows(ws, DISCARD_SCHEMA)
    if any(str(m.get("batch_id") or "") == batch for m in discards):
        return {"schema": COMMIT_SCHEMA, "appended": False,
                "reason": "batch-discarded", "batch_id": batch,
                "rollout_id": rid, "total_credit": 0.0,
                "dispatch_count": len(drafts)}
    total = round(sum(float(d.get("credit") or 0.0) for d in drafts), 6)
    marker = {
        "schema": COMMIT_SCHEMA,
        "ts": ts or _now(),
        "batch_id": batch,
        "rollout_id": rid,
        "total_credit": total,
    }
    appended = _cl.append(ws, "settlement", marker)
    return {"schema": COMMIT_SCHEMA, "appended": appended,
            "reason": None if appended else "append-refused",
            "batch_id": batch, "rollout_id": rid,
            "total_credit": total, "dispatch_count": len(drafts)}


def discard_drafts(ws, rollout_id: str, *, reason: str = "",
                   ts: str | None = None) -> dict:
    """The audited rollback: land a ``settlement-discard/1`` marker for
    the audit trail. The drafts themselves stay in the ledger (append-
    only) and the committed view excludes them by the missing commit
    marker — the discard marker only makes the DECISION auditable and
    blocks a later commit (never resurrect credit)."""
    rid = _non_empty(rollout_id, "rollout_id")
    batch = per_dispatch.batch_id(rid)
    if not draft_rows(ws, rid):
        return {"schema": DISCARD_SCHEMA, "appended": False,
                "reason": "no-drafts", "batch_id": batch,
                "rollout_id": rid}
    if any(str(m.get("batch_id") or "") == batch
           for m in _marker_rows(ws, COMMIT_SCHEMA)):
        return {"schema": DISCARD_SCHEMA, "appended": False,
                "reason": "already-committed", "batch_id": batch,
                "rollout_id": rid}
    discards = _marker_rows(ws, DISCARD_SCHEMA)
    if any(str(m.get("batch_id") or "") == batch for m in discards):
        return {"schema": DISCARD_SCHEMA, "appended": False,
                "reason": "already-discarded", "batch_id": batch,
                "rollout_id": rid}
    marker = {
        "schema": DISCARD_SCHEMA,
        "ts": ts or _now(),
        "batch_id": batch,
        "rollout_id": rid,
        "reason": str(reason),
    }
    appended = _cl.append(ws, "settlement", marker)
    return {"schema": DISCARD_SCHEMA, "appended": appended,
            "reason": None if appended else "append-refused",
            "batch_id": batch, "rollout_id": rid}


def _trajectory_terminal(ws, rid: str) -> str | None:
    """The rollout's terminal, derived from the trajectory ledger's own
    action rows (kind terminate_rollout → completed, rollback →
    rolled_back; append order, last wins). The face never takes the
    caller's word for the outcome."""
    terminal = None
    for row in q_cells.trajectory_rows(ws):
        if row.get("schema") != q_cells.SCHEMA_ACTION_V2:
            continue
        if str(row.get("rollout_id") or "") != rid:
            continue
        mapped = _TERMINAL_FROM_ACTION.get(str(row.get("kind") or ""))
        if mapped is not None:
            terminal = mapped
    return terminal


def committed_rollout(ws, rollout_id: str, *,
                      terminal_bonus: float = rollout_agg.TERMINAL_BONUS) \
        -> dict:
    """The committed aggregate read face: Σ(draft credits) + terminal
    for batches with a commit marker ONLY — an uncommitted (or
    discarded) rollout reads the honest empty (``committed: False``,
    zero totals, ``terminal: None``), never a fabricated figure.
    Stream tampering fails closed: a duplicate marker, a draft after
    the marker, or a foreign batch_id on a same-rollout draft raises —
    the read-time JOIN must never silently fold a tampered stream."""
    rid = _non_empty(rollout_id, "rollout_id")
    batch = per_dispatch.batch_id(rid)
    rows = _rows(ws)
    markers = [r for r in rows if r.get("schema") == COMMIT_SCHEMA
               and str(r.get("rollout_id") or "") == rid]
    empty = {"rollout_id": rid, "committed": False, "batch_id": batch,
             "dispatch_count": 0, "credits_sum": 0.0, "spend": 0.0,
             "total_spend": 0.0,
             "terminal": None, "terminal_adjustment": 0.0,
             "total_credit": 0.0}
    if not markers:
        return empty
    if len(markers) > 1:
        raise _fail("markers",
                    f"{len(markers)} commit markers for one batch — the "
                    f"append-only stream is tampered")
    marker = markers[0]
    if str(marker.get("batch_id") or "") != batch:
        raise _fail("markers.batch_id", "foreign batch identity")
    marker_at = rows.index(marker)
    joined: list[dict] = []
    for at, row in enumerate(rows):
        if row.get("schema") != DRAFT_SCHEMA \
                or str(row.get("rollout_id") or "") != rid:
            continue
        if at > marker_at:
            raise _fail("drafts",
                        f"a draft landed after the commit marker — the "
                        f"stream is tampered")
        if str(row.get("batch_id") or "") != batch:
            raise _fail("drafts.batch_id", "foreign batch identity")
        joined.append(row)
    terminal = _trajectory_terminal(ws, rid)
    if terminal is None:
        raise _fail("terminal",
                    f"rollout {rid!r} committed without a terminal "
                    f"action — the trajectory is incomplete")
    agg = rollout_agg.aggregate(joined, terminal=terminal,
                                terminal_bonus=terminal_bonus)
    return {"rollout_id": rid, "committed": True, "batch_id": batch,
            **agg}
