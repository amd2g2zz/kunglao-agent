# -*- coding: utf-8 -*-
"""workers/brief.py — the dispatch brief assembler (#885).

The second construction face: the orchestrator assembles the worker's
brief, and the brief CARRIES the knowledge — memory retrieval is
orchestrator-owned, so the worker never self-retrieves (the pinned
``retrieval: "orchestrator-owned"`` stamp documents the ownership; the
module has no retrieval face at all). Five sections, fixed order:

    goal    the goal excerpt (verbatim, non-empty)
    facts   the VERIFIED facts excerpt (orchestrator-retrieved)
    cards   the pattern cards (the crystallized method knowledge)
    budget  the Budget envelope (the worker's spend awareness)
    tools   the tool guidance

Deterministic: same inputs -> byte-identical brief; the ``brief_id``
content hash moves when the construction moves and never with the
wall clock (the #251 contract). Fail-closed at the boundary: a brief
with a blank goal, garbage budget or malformed sections is a brief
constructed to starve the worker — rejected loudly. Honest gaps (a
cold workspace's empty facts/cards) ride as EMPTY sections, never a
fabrication.
"""
from __future__ import annotations

import hashlib
import json
import math
import copy
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

_HERE = Path(__file__).resolve().parent.parent          # learning-loop/
_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
for _p in (_HERE, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from core import Budget  # noqa: E402 — the path bootstrap lands first

#: the receipt stamp — every brief names its schema (the audit face)
SCHEMA = "dispatch-brief/1"

#: the five brief sections in their fixed, deterministic order
SECTIONS: tuple[str, ...] = ("goal", "facts", "cards", "budget", "tools")


def _fail(field: str, why: str) -> ValueError:
    return ValueError(f"brief.{field}: {why}")


def _non_empty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail(field, "must be a non-empty string")
    return value


def _strings(values: Any, field: str) -> list[str]:
    """A string sequence — copied, in the caller's order (the
    orchestrator owns the ordering; this face never re-sorts its
    knowledge)."""
    if not isinstance(values, (list, tuple)):
        raise _fail(field, "must be a list of strings")
    out: list[str] = []
    for i, v in enumerate(values):
        if not isinstance(v, str) or not v.strip():
            raise _fail(f"{field}[{i}]", "must be a non-empty string")
        out.append(v)
    return out


def _cards(cards: Any, field: str = "cards") -> list[dict]:
    """The pattern cards — mapping + non-empty string ``id``, copies
    only (the same card contract the spawner constructs; an empty
    list is the honest cold-workspace gap)."""
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


def _budget(value: Any, field: str = "budget") -> Budget:
    """The envelope the worker is made aware of — a real core.Budget
    (finite, positive wall; optional call cap), not a number."""
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


def assemble_brief(goal: str, facts: Sequence[str], cards: Any,
                   budget: Budget, tools: Sequence[str]) -> dict:
    """Assemble the dispatch brief — the knowledge the worker RECEIVES
    (never retrieves). Pure data; deterministic; clock-free."""
    goal_v = _non_empty(goal, "goal")
    bud = _budget(budget)
    doc: dict[str, Any] = {
        "schema": SCHEMA,
        "retrieval": "orchestrator-owned",
        "sections": list(SECTIONS),
        "goal": goal_v,
        "facts": _strings(facts, "facts"),
        "cards": _cards(cards),
        "budget": {"wall_s": float(bud.wall_s),
                   "max_calls": bud.max_calls},
        "tools": _strings(tools, "tools"),
    }
    try:
        blob = json.dumps(doc, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise _fail("brief",
                    f"must be JSON-serializable ({type(exc).__name__}) "
                    f"— the brief id cannot hash it") from None
    doc["brief_id"] = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
    return doc
