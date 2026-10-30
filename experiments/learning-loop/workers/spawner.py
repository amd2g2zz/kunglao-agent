# -*- coding: utf-8 -*-
"""workers/spawner.py — the construction-style spawn preparer (#885).

Enforcement moves from INTERCEPTION to CONSTRUCTION: instead of
blocking a running worker's bad moves (the dispatch-gate posture,
removed by the #886 removal card), the spawner assembles the worker's
whole world BEFORE it runs — the frozen snapshot excerpt, the pattern
cards, the budget awareness and the time-box — so the violations the
old hooks guarded against cannot occur.

The spawn RECEIPT is the deliverable and the audit: every element the
worker was constructed with rides the receipt (逐句可归因), and its
content hash (``spawn_id``) is derived from that construction alone —
same construction, same receipt; the construction moved, the id moves;
never the wall clock (the #251 contract). The receipt carries the
explicit ``launch: "caller-owned"`` note: THIS face prepares, never
launches — the Agent-tool/process launch stays a caller concern (a
pure data face).

Fail-closed at the boundary (the episode_schema validator posture): a
worker constructed with a blank goal, a non-mapping snapshot, a
malformed card or a non-Budget/zero time-box is a worker constructed
to violate — rejected loudly, never tolerated.

Recording is the separate ``record_spawn`` face (the standard
single-writer append; kind = ``spawn_candidate``, the #878 closed
action space) — the spawner itself writes nothing.
"""
from __future__ import annotations

import hashlib
import json
import math
import copy
import sys
from pathlib import Path
from typing import Any, Mapping

_HERE = Path(__file__).resolve().parent.parent          # learning-loop/
_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
for _p in (_HERE, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from core import Budget  # noqa: E402 — the path bootstrap lands first
from rlvr import q_cells  # noqa: E402

#: the receipt stamp — every construction names its schema (the audit face)
SCHEMA = "spawn-receipt/1"


def _fail(field: str, why: str) -> ValueError:
    return ValueError(f"spawner.{field}: {why}")


def _non_empty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail(field, "must be a non-empty string")
    return value


def _budget(value: Any, field: str = "budget") -> Budget:
    """The construction envelope — a core.Budget with a REAL time-box:
    a worker constructed with a non-finite or non-positive wall budget
    is a worker constructed to violate; never built."""
    if not isinstance(value, Budget):
        raise _fail(field, "must be a core.Budget value object")
    wall = value.wall_s
    if isinstance(wall, bool) or not isinstance(wall, (int, float)) \
            or not math.isfinite(wall) or wall <= 0.0:
        raise _fail(f"{field}.wall_s", "must be a finite number > 0")
    mc = value.max_calls
    if mc is not None and (isinstance(mc, bool) or not isinstance(mc, int)
                           or mc < 1):
        raise _fail(f"{field}.max_calls", "must be None or an integer >= 1")
    return value


def _excerpt(snapshot: Any, field: str = "snapshot") -> dict:
    """The frozen snapshot excerpt — DEEP-copied so a later caller-side
    mutation (of any nested mapping) can never rewrite the audit;
    str-keyed (the canonical json identity below needs a stable
    sort)."""
    if not isinstance(snapshot, Mapping):
        raise _fail(field, "must be a mapping")
    if any(not isinstance(k, str) for k in snapshot):
        raise _fail(field, "every key must be a string")
    return copy.deepcopy(dict(snapshot))


def _cards(cards: Any, field: str = "cards") -> list[dict]:
    """The pattern cards — every card a mapping carrying a non-empty
    string ``id`` (the audit's card identity); DEEP copies, never
    the caller's objects or their nested mutables. An EMPTY list is
    the honest cold-workspace gap."""
    if not isinstance(cards, (list, tuple)):
        raise _fail(field, "must be a list of card mappings")
    out: list[dict] = []
    for i, card in enumerate(cards):
        if not isinstance(card, Mapping):
            raise _fail(f"{field}[{i}]", "must be a mapping")
        cid = card.get("id")
        if not isinstance(cid, str) or not cid.strip():
            raise _fail(f"{field}[{i}].id", "must be a non-empty string")
        out.append(copy.deepcopy(dict(card)))
    return out


def _content_id(receipt: Mapping, id_field: str) -> str:
    """The clock-free content identity: sha256 over the canonical
    receipt payload (sorted keys) MINUS the id itself."""
    payload = {k: receipt[k] for k in sorted(receipt) if k != id_field}
    try:
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise _fail("receipt",
                    f"must be JSON-serializable ({type(exc).__name__}) "
                    f"— the content id cannot hash it") from None
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def prepare_spawn(goal: str, snapshot: Mapping[str, Any],
                  cards: Any, budget: Budget, *,
                  worker_id: str) -> dict:
    """Assemble the worker's world BEFORE it runs — the receipt IS the
    audit of what the worker was constructed with. Pure data: no
    process is launched here, no clock is read."""
    goal_v = _non_empty(goal, "goal")
    worker_v = _non_empty(worker_id, "worker_id")
    bud = _budget(budget)
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "worker_id": worker_v,
        "goal": goal_v,
        "snapshot_excerpt": _excerpt(snapshot),
        "cards": _cards(cards),
        "budget": {"wall_s": float(bud.wall_s),
                   "max_calls": bud.max_calls},
        "time_box_s": float(bud.wall_s),
        "launch": "caller-owned",
    }
    receipt["spawn_id"] = _content_id(receipt, "spawn_id")
    return receipt


def record_spawn(ws, receipt: Mapping, *, rollout_id: str,
                 step_id: str | None = None,
                 policy_version: str | None = None) -> dict:
    """Land the construction as ONE ``q-cell-action/1`` row (kind =
    ``spawn_candidate``, the #878 action space) — the standard
    single-writer append; the ledger trusts the validated receipt."""
    if not isinstance(receipt, Mapping) or receipt.get("schema") != SCHEMA:
        raise _fail("receipt", f"must be a {SCHEMA!r} receipt")
    _non_empty(receipt.get("spawn_id"),
               "receipt.spawn_id (a hand-stamped receipt without the "
               "content id would record a hollow audit row)")
    return q_cells.append_action(
        ws, kind="spawn_candidate", rollout_id=rollout_id,
        step_id=step_id,
        target=_non_empty(receipt.get("worker_id"), "receipt.worker_id"),
        params={"spawn_id": receipt.get("spawn_id"),
                "goal": receipt.get("goal"),
                "snapshot_excerpt": receipt.get("snapshot_excerpt"),
                "cards": receipt.get("cards")},
        budget=receipt.get("budget"),
        policy_version=policy_version)
