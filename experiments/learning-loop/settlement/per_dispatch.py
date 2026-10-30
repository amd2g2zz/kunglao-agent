# -*- coding: utf-8 -*-
"""settlement/per_dispatch.py — ONE dispatch's settlement row (#884).

The three verification layers (mechanical checker → scope-verifier LLM
→ redteam) arrive as DATA: this face records their verdicts verbatim
and NEVER runs, re-orders, or re-litigates them — re-deciding another
face's verdict would be a second authority (the terminator coverage
posture). The face prices exactly ONE dispatch: the row carries the
dispatch's OWN spend (the ``cost`` of its own result row, never the
cumulative window the retired episode_settle.py booked) and the priced
credit — the conjunctive three-layer gate: every layer must pass for
the dispatch's result to stand (+1.0); any layer failing banks 0.0.
The gradient of WHICH layer failed belongs to the policy layer, not to
settlement.

Row identity: ``batch_id`` is deterministic over the rollout id. The
contract's example formula (rollout + sorted dispatch identities) is
unstable under incremental drafting — the dispatch set stays OPEN until
the terminator fires (#882), so a mid-rollout draft could never match
the rollout-end commit marker's digest; the batch IS the rollout's
draft set, so its identity pins to the rollout id alone (stable across
drafts, commits, and re-drafts, never clock-derived — the #251
contract). ``dispatch_id`` is the trajectory's ``step_id``: one
dispatch = one step of the (s,a,r) triple.

Fail-closed at the boundary: structural garbage (a missing layer, a
non-bool verdict, a negative spend) raises — a silently tolerated row
would fabricate credit in the ledger.
"""
from __future__ import annotations

import hashlib
import math
import sys
from pathlib import Path
from typing import Any, Mapping

_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from rlvr import q_cells  # noqa: E402 — the ledger read faces

#: the draft row's schema stamp (the receipt-stamp discipline —
#: terminator.py; the settlement family requires it at append).
DRAFT_SCHEMA = "settlement-draft/1"

#: the three verification layers, in gate order (mechanical → scope
#: verifier → redteam). Exactly these keys, no more, no fewer.
VERDICT_LAYERS = ("mechanical", "scope_verifier", "redteam")

#: the all-pass credit. A documented policy constant (NOT fitted), the
#: same governance class as terminator.LOSS_CUT_N.
PASS_CREDIT = 1.0


def _fail(field: str, why: str) -> ValueError:
    return ValueError(f"settlement.per_dispatch.{field}: {why}")


def _non_empty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail(field, "must be a non-empty string")
    return value


def _spend(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(value) or value < 0.0:
        raise _fail("spend", "must be a finite number >= 0")
    return float(value)


def _checked_verdicts(verdicts: Any) -> dict[str, bool]:
    """The verdicts wall: exactly the three layers, each a real bool
    (``1`` is a caller bug, not a pass). Recorded verbatim — the face
    is the settlement's scribe, never a fourth verification layer."""
    if not isinstance(verdicts, Mapping):
        raise _fail("verdicts", "must be a mapping keyed by layer")
    if set(verdicts) != set(VERDICT_LAYERS):
        raise _fail("verdicts",
                    f"must carry exactly {sorted(VERDICT_LAYERS)}, "
                    f"got {sorted(verdicts)}")
    for layer in VERDICT_LAYERS:
        if not isinstance(verdicts[layer], bool):
            raise _fail(f"verdicts.{layer}", "must be a bool")
    return {layer: verdicts[layer] for layer in VERDICT_LAYERS}


def _now() -> str:
    from harness_common import utc_now_z  # noqa: PLC0415 — the q_cells mirror
    return utc_now_z()


def batch_id(rollout_id: str) -> str:
    """The batch identity: sha256 over the rollout id. Deterministic,
    stable for the rollout's whole life (see the module docstring for
    why the dispatch identities stay out of the digest)."""
    rid = _non_empty(rollout_id, "rollout_id")
    digest = hashlib.sha256()
    digest.update(f"settlement-batch/1\n{rid}".encode("utf-8"))
    return digest.hexdigest()


def price_dispatch(rollout_id: str, dispatch_id: str, spend: Any,
                   verdicts: Mapping[str, bool], *,
                   ts: str | None = None) -> dict:
    """Price ONE dispatch into its draft row (pure — nothing lands):
    ``{schema, ts, batch_id, rollout_id, dispatch_id, spend, verdicts,
    credit}``. The credit is the conjunctive gate over the three
    recorded verdicts; the spend is THIS dispatch's own figure, never
    a cumulative window."""
    rid = _non_empty(rollout_id, "rollout_id")
    did = _non_empty(dispatch_id, "dispatch_id")
    spend_out = round(_spend(spend), 6)
    v = _checked_verdicts(verdicts)
    credit = PASS_CREDIT if all(v.values()) else 0.0
    return {
        "schema": DRAFT_SCHEMA,
        "ts": ts or _now(),
        "batch_id": batch_id(rid),
        "rollout_id": rid,
        "dispatch_id": did,
        "spend": spend_out,
        "verdicts": v,
        "credit": credit,
    }


def dispatch_spend(ws, rollout_id: str, dispatch_id: str) -> float:
    """The dispatch's OWN spend from the trajectory ledger — the
    ``cost`` of its LAST result row (append order; the reversed scan
    mirrors q_cells._match_pending_dispatch). Missing row → ValueError:
    a settlement without a trajectory is a fabrication. Same-rollout
    rows only; other rollouts' costs never leak in."""
    rid = _non_empty(rollout_id, "rollout_id")
    did = _non_empty(dispatch_id, "dispatch_id")
    for row in reversed(q_cells.trajectory_rows(ws)):
        if row.get("schema") != q_cells.SCHEMA_RESULT_V2:
            continue
        if str(row.get("rollout_id") or "") != rid \
                or str(row.get("step_id") or "") != did:
            continue
        cost = row.get("cost")
        if isinstance(cost, bool) or not isinstance(cost, (int, float)) \
                or not math.isfinite(cost):
            raise _fail("cost",
                        f"result row of ({rid}, {did}) carries a "
                        f"non-finite cost")
        return float(cost)
    raise _fail("dispatch",
                f"no result row for ({rid}, {did}) — nothing to settle")
