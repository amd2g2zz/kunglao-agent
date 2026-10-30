# -*- coding: utf-8 -*-
"""credit/lineage.py — spawned-task credit flowback.

A rollout that spawned candidate tasks does not own its return alone:
each child's credited return flows back to its parent at the lineage
γ (the spawning decision EARNED the child's outcome, discounted by
the distance). The chain is the rollout-id parent map — data the loop
supplies from its own spawn records (kind=spawn_candidate actions),
never reconstructed here. Reverse-topological order guarantees every
child is credited before its parent reads it; a cycle is a caller
bug and raises (a cycle would otherwise loop the flowback forever).
"""
from __future__ import annotations

from typing import Mapping


def _checked_returns(ret: Mapping[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for k, v in ret.items():
        key = str(k or "").strip()
        if not key:
            raise ValueError("credit.lineage: rollout ids must be "
                             "non-empty")
        f = float(v)
        if f != f or f in (float("inf"), float("-inf")):
            raise ValueError(
                f"credit.lineage: return for {key!r} must be finite")
        out[key] = f
    if not out:
        raise ValueError("credit.lineage: the return map is empty")
    return out


def flowback(ret: Mapping[str, float],
             parent_of: Mapping[str, str | None],
             *, gamma_lineage: float) -> dict[str, float]:
    """Credited returns up the spawn chain: credited(n) = own(n) +
    γ_L · Σ credited(children). Orphan parents (ids with no return of
    their own) still route their children's credit — the map's keys
    define the frontier. γ_L in (0, 1); a cycle raises."""
    g = float(gamma_lineage)
    if not 0.0 < g < 1.0:
        raise ValueError(
            f"credit.lineage: gamma_lineage must lie in (0, 1), "
            f"got {gamma_lineage!r}")
    own = _checked_returns(ret)
    parent: dict[str, str | None] = {}
    for k, v in parent_of.items():
        key = str(k or "").strip()
        if not key:
            raise ValueError(
                "credit.lineage: parent-map keys must be non-empty")
        parent[key] = str(v).strip() if v else None

    credited: dict[str, float] = {}
    in_progress: set[str] = set()

    def resolve(node: str) -> float:
        if node in credited:
            return credited[node]
        if node in in_progress:
            raise ValueError(
                f"credit.lineage: spawn cycle through {node!r}")
        in_progress.add(node)
        total = own.get(node, 0.0)
        for child, par in parent.items():
            if par == node:
                total += g * resolve(child)
        in_progress.discard(node)
        credited[node] = total
        return total

    return {node: resolve(node) for node in own}
