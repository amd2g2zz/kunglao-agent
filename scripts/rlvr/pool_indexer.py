# -*- coding: utf-8 -*-
"""rlvr/pool_indexer.py — the pool's DERIVED VIEWS (issue 824, P1).

The value table and the playbook view are projections over the episode
files (A3: growth = the views sharpen and compound, the pool thickens)
— they own NO storage: they compute over runs/episodes/ at call time,
in deterministic order, and write nothing (the no-parallel-store pin:
regenerate = identical output, no new file).

VALUE TABLE — `context_features x commit action -> {n, mean_reward,
mean_cost}`: the learner's value statistics (the #806 axis demotes the
context-free family bandit to a cold-start prior; THIS is the
contextual successor). Only episodes with a stamped `reward.r`
contribute to a cell (an honest gap — unstamped episodes carry no
output signal yet); ``n`` is the DISTINCT-EPISODE count per cell (one
mission = one count — commit rows of the same episode amend, never
multiply); mean_cost is the normalized cost term in [0, 1].

PLAYBOOK VIEW — successful-episode compression, the legitimate form of
distillation: episodes with a verified completion, grouped by sorted
context features, emitting their deduped reusable fragments (capped
per group at PLAYBOOK_FRAGMENTS_CAP). Admissions follow the pool's own
trust spine: `outcome.status == completed` AND the outcome evidence
resolving to a PASSED record (verifier_integrity, called not
modified). Deep compression (merging, paraphrase, ordering heuristics)
is P3 — this card pins the admission + dedupe + cap rules only.

Zero telemetry points (Standard 11). No mutation of the pool.
"""
from __future__ import annotations

from pathlib import Path

from rlvr import episode_pool as pool
from rlvr import reward_signal

#: the playbook group's fragment cap (deep compression is P3)
PLAYBOOK_FRAGMENTS_CAP = 12


def cell_key(features: tuple[str, ...] | list[str], action: str) -> tuple:
    """The value-table cell key: (sorted context features, commit
    action). Exposed so consumers build keys through ONE face."""
    return (tuple(sorted(str(f) for f in features)), str(action))


def value_table(ws) -> dict[tuple, dict]:
    """context-features x action -> {n, mean_reward, mean_cost} over the
    pool's reward-stamped episodes. ``n`` counts DISTINCT EPISODES per
    cell — one mission = one count (a mission's several same-action
    commit rows amend the cell once, never multiply it; the P7-confirmed
    inflation where n counted commit rows is fixed here). Deterministic;
    writes nothing."""
    sums: dict[tuple, dict] = {}
    seen: dict[tuple, set] = {}
    for path, doc in pool.load_all(ws):
        reward = doc.get("reward") or {}
        # the stamped mission reward may ride as a bare float (the
        # reward_block carries the decomposition) — read both shapes.
        r = reward.get("r") if isinstance(reward, dict) else reward
        if not isinstance(r, (int, float)) or isinstance(r, bool):
            continue  # unstamped: no output signal yet (honest gap)
        cost = doc.get("cost") or {}
        cost_term = reward_signal.cost_term(cost.get("tokens") or 0.0,
                                            cost.get("seconds") or 0.0)
        eid = str(doc.get("id") or path.name)
        for c in doc.get("commits") or []:
            key = cell_key(doc.get("context_features") or [],
                           c.get("action"))
            contributors = seen.setdefault(key, set())
            if eid in contributors:
                continue  # identity amends, it does not multiply
            contributors.add(eid)
            cell = sums.setdefault(key, {"n": 0, "sum_reward": 0.0,
                                         "sum_cost": 0.0})
            cell["n"] += 1
            cell["sum_reward"] += float(r)
            cell["sum_cost"] += float(cost_term)
    return {
        key: {"n": cell["n"],
              "mean_reward": cell["sum_reward"] / cell["n"],
              "mean_cost": cell["sum_cost"] / cell["n"]}
        for key, cell in sorted(sums.items())
    }


def _completed_verified(ws, doc: dict) -> bool:
    if doc.get("outcome", {}).get("status") != "completed":
        return False
    try:
        from verifier_integrity import resolve_verification  # noqa: PLC0415
        passed, _w, _d = resolve_verification(
            ws, str(doc.get("claim")),
            doc.get("outcome", {}).get("evidence_ref") or "")
        return passed
    except Exception:  # noqa: BLE001 — resolver fault excludes (fail-closed)
        return False


def playbook_view(ws) -> list[dict]:
    """Successful-episode compression: verified completions grouped by
    sorted context features -> deduped, capped reusable fragments.
    Deterministic; writes nothing."""
    groups: dict[tuple, list[str]] = {}
    for _path, doc in pool.load_all(ws):
        if not _completed_verified(Path(ws), doc):
            continue
        key = tuple(sorted(str(f)
                           for f in doc.get("context_features") or []))
        frags = groups.setdefault(key, [])
        for f in doc.get("reusable_fragments") or []:
            if f not in frags:
                frags.append(f)
    return [{"context_features": list(key),
             "fragments": frags[:PLAYBOOK_FRAGMENTS_CAP]}
            for key, frags in sorted(groups.items())]
