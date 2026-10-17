# -*- coding: utf-8 -*-
"""decision_view.py — THE decision view-model contract (one model
layer, two views).

The RL decides every round (which claim to rank, what just settled, how
much budget remains) and the workbench will render that story twice —
first through a TUI, later through a Web view (the workbench track's
"one model layer, two views" shape). This module IS the model layer: a
single `build_view(ws)` assembly of the six faces an operator needs at
a glance, each read from an existing single-source face — never a
second derivation:

    in_flight         register claims in IN_PROGRESS plus the round's
                      leading method family (the strategy object)
    why_this_one      the newest rank run's top claim: score, feeds,
                      decision entropy / propensity / k (the additive
                      rank_feeds payload keys), and rank recency
    just_settled      the newest settled rollout (anchor / kind / band /
                      reward / ts)
    hypothesis_space  arm counts by canonical status class plus the
                      frontier entropy face (entropy_face single source)
    budget            token / tool_calls / verify_calls — honest nulls
                      with accounted False while cost stays
                      diagnostic-only upstream
    next_candidates   top-ranked claims with scores and dispatch tiers,
                      sliced to VIEW_TOP_K

Contract: SCHEMA stamps the shape; FACES pins the face order; FACE_KEYS
pins each face's exact key set; ABSENT documents each face's absent
shape. build_view NEVER raises — a source that is missing, unreadable,
or raising degrades ITS face to the absent shape (keys present, honest
nulls) behind one canonical warn; the other faces still build. Old rank
events written before the additive payload keys degrade the same way
(entropy / propensity null, k derived from the ranked order, per-row
tier null).

Dual-use rule (every displayed metric is decision-consumed): the faces
are pure reads of persisted single sources — a renderer never
recomputes, and this module never writes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from kunglao_log import warn  # canonical warn: ONE implementation
import entropy_face
import rank_face
from _scriptlib import read_register_claims
from retract_claim import RETRACTED
from status_defs import (ACTIVE_STATUSES, IN_PROGRESS_STATUSES,
                         PARTIAL_STATUSES, SUSPENDED, TERMINAL)

SCHEMA = "decision-view/1"

#: the face order an operator reads: what is running, why that choice,
#: what just landed, what the hypothesis space looks like, what budget
#: remains, what comes next.
FACES = ("in_flight", "why_this_one", "just_settled",
         "hypothesis_space", "budget", "next_candidates")

#: the exact key set every face carries — present in every build_view
#: result, absent shapes included (a renderer keys off this contract,
#: never off file existence).
FACE_KEYS = {
    "in_flight": ("claims", "count", "method_lead"),
    "why_this_one": ("claim", "score", "entropy", "propensity", "k",
                     "feeds", "ts", "age_s", "stale"),
    "just_settled": ("anchor", "kind", "band", "reward", "ts", "age_s"),
    "hypothesis_space": ("alive", "parked", "pruned", "terminal", "other",
                         "h_bits", "h_pq", "h_trend"),
    "budget": ("tokens", "tool_calls", "verify_calls", "accounted"),
    "next_candidates": ("k", "candidates"),
}

#: next_candidates carries at most this many rows — the glanceable
#: shortlist; `k` on the same face records the FULL candidate count, so
#: a renderer wanting more re-slices the payload's ranked order without
#: a re-rank.
VIEW_TOP_K = 5

#: each face's documented absent shape (keys present, honest nulls) —
#: the fail-open contract's landing pad and the tests' pin.
ABSENT = {
    "in_flight": {"claims": [], "count": 0, "method_lead": None},
    "why_this_one": {"claim": None, "score": None, "entropy": None,
                     "propensity": None, "k": None, "feeds": {},
                     "ts": None, "age_s": None, "stale": True},
    "just_settled": {"anchor": None, "kind": None, "band": None,
                     "reward": None, "ts": None, "age_s": None},
    "hypothesis_space": {"alive": 0, "parked": 0, "pruned": 0,
                         "terminal": 0, "other": 0, "h_bits": None,
                         "h_pq": None, "h_trend": "unknown"},
    "budget": {"tokens": None, "tool_calls": None, "verify_calls": None,
               "accounted": False},
    "next_candidates": {"k": None, "candidates": []},
}


# ------------------------------------------------------------- helpers

def _age_s(ts, now: datetime) -> float | None:
    """Seconds between an ISO-8601 instant and `now` (1dp, floor 0);
    None when the stamp is absent or unparseable (honest unknown)."""
    if not isinstance(ts, str):
        return None
    try:
        then = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return round(max(0.0, (now - then).total_seconds()), 1)


def _method_lead(ws: Path) -> str | None:
    """The round strategy's leading method family; None when no strategy
    object exists, its schema is unknown, or the field is empty
    (fail-open — the family is context, never a gate)."""
    try:
        from rlvr import compose  # lazy: the package is heavier than a face
        doc = compose.read_strategy(ws)
    except Exception as exc:  # noqa: BLE001 — a face never breaks its caller
        warn("decision_view.strategy", f"{type(exc).__name__}: {exc}")
        return None
    if not isinstance(doc, dict) or doc.get("schema") != compose.SCHEMA:
        return None
    dispatch = doc.get("dispatch")
    lead = dispatch.get("method_lead") if isinstance(dispatch, dict) else None
    if lead is None:
        return None
    lead = str(lead).strip()
    return lead or None


# ------------------------------------------------------------- faces

def _in_flight(ws: Path, payload_doc: dict, now: datetime) -> dict:
    """Who is doing what right now: the claims a worker holds
    (IN_PROGRESS) and the round's leading method family."""
    claims = [c for c in read_register_claims(ws)
              if str(c.get("status") or "").upper() in IN_PROGRESS_STATUSES
              and c.get("id")]
    return {"claims": [str(c["id"]) for c in claims],
            "count": len(claims),
            "method_lead": _method_lead(ws)}


def _rank_k(payload: dict) -> int | None:
    """The persisted candidate count; legacy rows (written before the
    additive keys) derive it from the ranked order, an absent row stays
    None (no run is not the same as a run with zero candidates)."""
    k = payload.get("k")
    if isinstance(k, int) and not isinstance(k, bool):
        return k
    order = payload.get("ranked_order")
    return len(order) if isinstance(order, list) and order else None


def _why_this_one(ws: Path, payload_doc: dict, now: datetime) -> dict:
    """The selection rationale: the newest rank run's top claim, its
    score, its feeds diagnostic, the persisted decision entropy /
    propensity / k, and the run's recency."""
    payload = payload_doc.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {}
    order = payload.get("ranked_order") or []
    claim = order[0] if isinstance(order, list) and order else None
    if not isinstance(claim, str):
        claim = None
    scores = payload.get("scores") or {}
    feeds = payload.get("feeds") or {}
    score = scores.get(claim) if isinstance(scores, dict) and claim else None
    top_feeds = feeds.get(claim) if isinstance(feeds, dict) and claim else None
    return {"claim": claim,
            "score": (float(score)
                      if isinstance(score, (int, float))
                      and not isinstance(score, bool) else None),
            "entropy": payload.get("entropy"),
            "propensity": payload.get("propensity"),
            "k": _rank_k(payload),
            "feeds": dict(top_feeds) if isinstance(top_feeds, dict) else {},
            "ts": payload_doc.get("ts"),
            "age_s": payload_doc.get("age_s"),
            "stale": bool(payload_doc.get("stale", True))}


def _just_settled(ws: Path, payload_doc: dict, now: datetime) -> dict:
    """The newest settled rollout — the settlement ledger tail, the same
    single source the RL digest line reads. The newest row wins."""
    try:
        from rlvr import ledger as rl  # lazy: the package is heavier
        rows = rl.settled(ws)
    except Exception as exc:  # noqa: BLE001 — a face never breaks its caller
        warn("decision_view.settled", f"{type(exc).__name__}: {exc}")
        rows = []
    if not rows:
        return dict(ABSENT["just_settled"])
    row = rows[-1]
    settlement = row.get("settlement") or {}
    anchor = str(row.get("anchor") or row.get("rollout_id") or "").strip()
    ts = row.get("ts") if isinstance(row.get("ts"), str) else None
    return {"anchor": anchor or None,
            "kind": row.get("kind") if isinstance(row.get("kind"), str)
            else None,
            "band": settlement.get("band") if isinstance(settlement, dict)
            else None,
            "reward": settlement.get("reward") if isinstance(settlement, dict)
            else None,
            "ts": ts,
            "age_s": _age_s(ts, now)}


def _hypothesis_space(ws: Path, payload_doc: dict, now: datetime) -> dict:
    """The hypothesis space: arm counts by canonical status class
    (alive = dispatchable/in-progress, parked = suspended, pruned =
    retracted, terminal = the frozen terminal set, other = anything
    unclassifiable — counted, never hidden) plus the frontier entropy
    face's own keys (entropy_face single source)."""
    counts = {"alive": 0, "parked": 0, "pruned": 0, "terminal": 0,
              "other": 0}
    for claim in read_register_claims(ws):
        status = str(claim.get("status") or "").upper()
        if status in TERMINAL:
            counts["terminal"] += 1
        elif status == RETRACTED:
            counts["pruned"] += 1
        elif status in SUSPENDED:
            counts["parked"] += 1
        elif status in ACTIVE_STATUSES or status in PARTIAL_STATUSES:
            counts["alive"] += 1
        else:
            counts["other"] += 1
    ent = entropy_face.face(ws)
    return {**counts,
            "h_bits": ent.get("h_bits"),
            "h_pq": ent.get("h_pq"),
            "h_trend": ent.get("h_trend")}


def _budget(ws: Path, payload_doc: dict, now: datetime) -> dict:
    """The three budget slots. Cost accounting is the documented
    upstream blocker (cost is diagnostic-only today), so every slot is
    a null and accounted is False — an honest absent face, never
    fabricated zeros a renderer would mistake for spend."""
    return dict(ABSENT["budget"])


def _next_candidates(ws: Path, payload_doc: dict, now: datetime) -> dict:
    """The next candidates: the newest run's ranked order projected to
    {claim, score, tier} rows (the additive tiers key) sliced to
    VIEW_TOP_K; `k` stays the FULL persisted candidate count."""
    payload = payload_doc.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {}
    order = payload.get("ranked_order") or []
    if not isinstance(order, list):
        order = []
    scores = payload.get("scores") if isinstance(payload.get("scores"),
                                                  dict) else {}
    tiers = payload.get("tiers") if isinstance(payload.get("tiers"),
                                               dict) else {}

    def _row(cid: str) -> dict:
        score = scores.get(cid)
        tier = tiers.get(cid)
        return {"claim": cid,
                "score": (float(score)
                          if isinstance(score, (int, float))
                          and not isinstance(score, bool) else None),
                "tier": tier if isinstance(tier, int)
                and not isinstance(tier, bool) else None}

    candidates = [_row(cid) for cid in order
                  if isinstance(cid, str)][:VIEW_TOP_K]
    return {"k": _rank_k(payload), "candidates": candidates}


_BUILDERS = {
    "in_flight": _in_flight,
    "why_this_one": _why_this_one,
    "just_settled": _just_settled,
    "hypothesis_space": _hypothesis_space,
    "budget": _budget,
    "next_candidates": _next_candidates,
}


# ------------------------------------------------------------- the model

def build_view(ws, *, now: datetime | None = None) -> dict:
    """The six-face decision view: ``{"schema", "faces"}`` with every
    FACES entry carrying exactly its FACE_KEYS set.

    Fail-open by contract: each face builds behind its own guard — a
    missing, unreadable, or raising source degrades THAT face to its
    ABSENT shape (keys present, honest nulls) behind one canonical
    warn, and build_view itself never raises. The rank payload is read
    once through rank_face (the single source that owns the rank event
    read) and shared by the two rank-derived faces, so they can never
    disagree about which run they describe."""
    ws = Path(ws)
    now = now or datetime.now(timezone.utc)
    try:
        payload_doc = rank_face.latest_payload(ws, now=now)
    except Exception as exc:  # noqa: BLE001 — a view never breaks its caller
        warn("decision_view.rank", f"{type(exc).__name__}: {exc}")
        payload_doc = {"payload": {}, "ts": None, "age_s": None, "stale": True}
    faces = {}
    for name in FACES:
        try:
            faces[name] = _BUILDERS[name](ws, payload_doc, now)
        except Exception as exc:  # noqa: BLE001 — per-face fail-open
            warn("decision_view." + name, f"{type(exc).__name__}: {exc}")
            faces[name] = dict(ABSENT[name])
    return {"schema": SCHEMA, "faces": faces}
