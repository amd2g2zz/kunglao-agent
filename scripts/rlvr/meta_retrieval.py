# -*- coding: utf-8 -*-
"""meta_retrieval.py — the pool retrieval AT the decision points (the
meta-policy rewire's context half).

The P1 pool read face (`episode_pool.retrieve`) is legal at exactly
three phases; this module is the DECISION-FACING wrapper: it retrieves
at the phase, ranks the matched cases by the utility-score weights
(knob group b), filters by the retrieval threshold, caps by the context
budget (knob group c), and attaches the feature-matched playbook view
fragments. The output rides the dispatch envelope's meta-policy block —
the executor's in-context learning is FED, not bypassed (#806 axis).

Ablation: KUNGLAO_META_RETRIEVAL=0 removes the retrieval component —
no retrieve call (the pool counters stay untouched), no cases, no
playbook; the budget block still reports the (inactive) budget.

Zero telemetry points (Standard 11). No storage: the cases' utility
counters are the pool's own faces (retrieval bumps them; settlement
decays/revalues them).
"""
from __future__ import annotations

from pathlib import Path

from rlvr import episode_pool as pool
from rlvr import pool_indexer

#: playbook groups ride the same context budget (the executor reads
#: cases + playbook within one budget; documented, not fitted)
PLAYBOOK_GROUPS_CAP = 2


def _knobs(knobs: dict | None) -> dict:
    if knobs is not None:
        return knobs
    from rlvr import meta_policy  # noqa: PLC0415 — lazy (cycle-free)
    return meta_policy.knobs()


def utility_score(doc: dict, k: dict) -> float:
    """The utility-score face (knob group b): saturated citation and
    retrieval masses under the learnable weights, plus the pool's own
    decayed utility."""
    util = doc.get("utility") or {}
    citations = max(0, int(util.get("citations") or 0))
    retrievals = max(0, int(util.get("retrievals") or 0))
    cit = citations / (citations + 1.0)
    ret = retrievals / (retrievals + 1.0)
    stored = float(util.get("utility") or 0.0)
    return (k["w_citation"] * cit + k["w_retrieval"] * ret + stored)


def assemble(ws, features: list[str], *, phase: str,
             knobs: dict | None = None) -> dict:
    """The decision-facing retrieval: phase-legal pool retrieve ->
    utility-score rank -> threshold filter -> budget cap; the playbook
    view attaches alongside. Refuses illegal phases (the pool's own
    refusal propagates)."""
    k = _knobs(knobs)
    budget = {"max_cases": int(k["retrieve_max"]),
              "min_utility": float(k["min_utility"]),
              "retrieval": bool(k["retrieval"])}
    if not k["retrieval"]:
        return {"cases": [], "playbook": [], "budget": budget}

    ws = Path(ws)
    matched = pool.retrieve(ws, features, phase=phase)
    ranked = sorted(
        matched,
        key=lambda doc: (-utility_score(doc, k), str(doc.get("claim"))))
    cases: list[dict] = []
    for doc in ranked:
        if float(doc.get("utility", {}).get("utility") or 0.0) \
                < float(k["min_utility"]):
            continue
        if len(cases) >= int(k["retrieve_max"]):
            break
        fragments = [str(f) for f in doc.get("reusable_fragments") or []]
        cases.append({"claim": str(doc.get("claim")),
                      "utility": float(doc.get("utility", {})
                                       .get("utility") or 0.0),
                      "summary": fragments[0] if fragments else ""})

    playbook: list[dict] = []
    for group in pool_indexer.playbook_view(ws):
        group_feats = {str(f)
                       for f in group.get("context_features") or []}
        if not group_feats & {str(f) for f in features}:
            continue
        playbook.append(group)
        if len(playbook) >= PLAYBOOK_GROUPS_CAP:
            break
    return {"cases": cases, "playbook": playbook, "budget": budget}
