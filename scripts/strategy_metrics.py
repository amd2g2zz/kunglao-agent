#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""strategy_metrics.py — #529 strategy convergence four metrics.

Pure functions (zero LLM, no I/O) layered atop priority_ratio.Action /
EvidenceView.  Four metrics answer four orthogonal convergence questions:

  regret            Reverse-regret vs an oracle action selection:
                    difference between the oracle's best-score action and
                    the action actually picked.  Tracked over a window,
                    convergence is "regret → 0".  Spec: regret(picked,
                    oracle) = score(oracle) − score(picked).

  cost_to_slope     Efficient-frontier curve: cumulative score gained
                    per additional unit of cost; the slope Δscore/Δcost
                    on the rank-by-cost frontier.  Convergence is
                    "diminishing returns" — last slope ≤ first slope.

  p_faster_given_hit  Conditional probability: given a claim produced a
                    hit (PROVEN fact), what's the probability it actually
                    finished faster than the median hit?  Convergence is
                    "P(faster|hit) → 1" (every hit is accelerated).

  competence_coverage  Fraction of required tool families that the
                    validated_capability cards already cover.  Convergence
                    is "coverage → 1" (no missing families).

Inputs are plain dicts (claim_id / score / cost etc.) — the functions
deliberately DO NOT import priority_ratio at module load time so the
metrics remain embeddable in scripts that don't need the full ranking
machinery.  Composite helper `compute_all` returns a snapshot dict.

Usage:
  from strategy_metrics import regret, cost_to_slope, p_faster_given_hit, competence_coverage  # noqa
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

__all__ = [
    "regret",
    "cost_to_slope",
    "p_faster_given_hit",
    "competence_coverage",
    "compute_all",
    "snapshot_for_workspace",
    "_median",
]


# ---------- regret ----------

def regret(actions: list[dict], picked: set[str], oracle: set[str]) -> dict:
    """Reverse-regret vs. oracle selection.

    regret = score(oracle_top) − score(picked_top), bounded below by 0.
    Empty actions → 0 (trivially converged).  Multi-action oracle/picked
    supported: top score wins on each side; missing top → use 0.

    Returns {"regret": float, "picked": list[str], "oracle": list[str]} —
    the picked/oracle echoes aid debugging the metric when it spikes.
    """
    if not actions:
        return {"regret": 0.0, "picked": [], "oracle": []}

    def _top(ids: set[str]) -> tuple[float, str | None]:
        if not ids:
            return 0.0, None
        ranked = [a for a in actions if a.get("claim_id") in ids]
        if not ranked:
            return 0.0, None
        ranked.sort(key=lambda a: a.get("score", 0.0), reverse=True)
        return ranked[0].get("score", 0.0), ranked[0].get("claim_id")

    oracle_score, oracle_id = _top(oracle)
    picked_score, picked_id = _top(picked)
    # both empty → 0; else subtract
    if oracle_id is None and picked_id is None:
        return {"regret": 0.0, "picked": [], "oracle": []}
    loss = oracle_score - picked_score
    if loss < 0:
        loss = 0.0  # negative regret → picked beat oracle (just luck / ahead of information)
    return {
        "regret": round(float(loss), 6),
        "picked": [picked_id] if picked_id else [],
        "oracle": [oracle_id] if oracle_id else [],
    }


# ---------- cost_to_slope ----------

def cost_to_slope(actions: list[dict]) -> list[dict]:
    """Efficient-frontier curve: per-action Δscore/Δcost.

    Sorted by cost ascending; computes prefix sums, then per-step
    marginal slope (cumulative Δscore / cumulative Δcost).  First row is
    always `slope=None` (cannot form a slope with one point) so callers
    can drop it without indexing errors.

    Returns list[{"claim_id", "cost", "score", "cum_score", "cum_cost", "slope"}].
    Empty input → [].
    """
    if not actions:
        return []
    sorted_actions = sorted(actions, key=lambda a: (a.get("cost", 0.0), a.get("claim_id", "")))
    rows: list[dict] = []
    prev_cum_score = 0.0
    prev_cum_cost = 0.0
    first = True
    for a in sorted_actions:
        cost = float(a.get("cost", 0.0))
        score = float(a.get("score", 0.0))
        cum_score = prev_cum_score + score
        cum_cost = prev_cum_cost + cost
        if first:
            slope = None
        else:
            d_score = cum_score - prev_cum_score
            d_cost = cum_cost - prev_cum_cost
            slope = (d_score / d_cost) if d_cost > 0 else None
        rows.append({
            "claim_id": a.get("claim_id"),
            "cost": cost,
            "score": score,
            "cum_score": round(cum_score, 6),
            "cum_cost": round(cum_cost, 6),
            "slope": round(slope, 6) if slope is not None else None,
        })
        prev_cum_score = cum_score
        prev_cum_cost = cum_cost
        first = False
    return rows


# ---------- P(faster | hit) ----------

def _median(values: Iterable[float]) -> float:
    """Median of a finite iterable.  Empty → 0.0 (no signal)."""
    vs = sorted(values)
    n = len(vs)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2:
        return float(vs[mid])
    return (vs[mid - 1] + vs[mid]) / 2.0


def p_faster_given_hit(hits: list[float], median_hit_time: float | None = None) -> dict:
    """Conditional P(faster | hit) — fraction of hits faster than median.

    If median_hit_time is omitted, compute it from the hits directly
    (defined only when n > 0; the test pins an explicit median so the
    formula is reproducible against a fixed reference).

    Returns {"p_faster": float, "hits": int, "median": float}.
    """
    if not hits:
        return {"p_faster": 0.0, "hits": 0, "median": 0.0}
    median = median_hit_time if median_hit_time is not None else _median(hits)
    if median <= 0:
        # pathological: zero-or-negative median ⇒ degenerate; treat as no signal
        return {"p_faster": 0.0, "hits": len(hits), "median": median}
    faster = sum(1 for t in hits if t < median)
    return {
        "p_faster": round(faster / len(hits), 6),
        "hits": len(hits),
        "median": round(float(median), 6),
    }


# ---------- competence coverage ----------

def competence_coverage(validated_families: set[str], required_families: set[str]) -> dict:
    """Coverage = |validated ∩ required| / |required|.

    Empty required → 1.0 (trivially covered; nothing missing by definition).
    All-required-missing → 0.0 with every required family echoed in
    `missing` (sorted) for the dispatch gate to consume.

    Returns {"coverage": float, "missing": list[str], "validated": list[str]}.
    """
    validated = {str(f) for f in (validated_families or set())}
    required = {str(f) for f in (required_families or set())}
    if not required:
        return {"coverage": 1.0, "missing": [], "validated": sorted(validated)}
    missing = sorted(required - validated)
    covered = required & validated
    return {
        "coverage": round(len(covered) / len(required), 6),
        "missing": missing,
        "validated": sorted(validated),
    }


# ---------- composite ----------

def compute_all(actions: list[dict], picked: set[str], oracle: set[str],
                hits: list[float] | None = None,
                validated_families: set[str] | None = None,
                required_families: set[str] | None = None) -> dict:
    """Bundle the four metrics into one snapshot dict.

    Optional inputs (hits / families) default empty; p_faster_given_hit
    and competence_coverage each degrade to their trivial defaults.
    """
    return {
        "regret": regret(actions, picked, oracle),
        "cost_to_slope": cost_to_slope(actions),
        "p_faster_given_hit": p_faster_given_hit(hits or []),
        "competence": competence_coverage(validated_families or set(),
                                          required_families or set()),
    }


# ---------- integration helpers (workspace-backed; optional) ----------

def snapshot_for_workspace(workspace: Path,
                           picked: set[str] | None = None,
                           oracle: set[str] | None = None,
                           hits: list[float] | None = None,
                           required_families: set[str] | None = None) -> dict:
    """Read-only integration with priority_ratio + EvidenceView.

    Loads claim-register.yaml + claim_deps.yaml, runs priority_ratio to
    produce the action list, then assembles the four-metric snapshot
    from the workspace artefacts (#495 validated_capability cards + the
    optional hit_times file).  All four inputs are optional; the
    corresponding metric degrades to its no-signal default.

    Required-families defaults to nothing (the metric reports coverage=1.0
    until the workspace declares requirements — its own contract: the
    metric cannot fail closed without an explicit requirement list)."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import priority_ratio as pr  # noqa: WPS433 — workspace integration
    except ImportError:
        return compute_all([], picked or set(), oracle or set(),
                           hits or [], set(), required_families or set())

    import yaml  # local import: keeps the metric module stdlib/yaml-light

    ws = Path(workspace)
    reg = (yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8")) or {}) \
        if (ws / "claim-register.yaml").exists() else {}
    deps = (yaml.safe_load((ws / "claim_deps.yaml").read_text(encoding="utf-8")) or {}) \
        if (ws / "claim_deps.yaml").exists() else {}
    claims = reg.get("claims") or []
    evidence = pr.EvidenceView.from_workspace(ws)
    actions = pr.priority_ratio(claims, deps, evidence)
    action_dicts = [a.to_dict() for a in actions]
    validated = {fam for _, text in evidence.validated_capabilities
                 for fam in _families_from_text(text)}
    return compute_all(
        actions=action_dicts,
        picked=picked or set(),
        oracle=oracle or set(),
        hits=hits or [],
        validated_families=validated,
        required_families=required_families or set(),
    )


_FAMILY_TOKENS = ("frida", "xposed", "lsposed", "ghidra", "ida",
                  "idapython", "x64dbg", "ollydbg", "volatility",
                  "vmr-shell", "vmrun", "qiling", "malware-framework")


def _families_from_text(text: str) -> set[str]:
    """Best-effort family extraction from validated_capability text.
    ASCII word-bounded; mirrors priority_ratio's vocabulary."""
    import re
    found: set[str] = set()
    for tok in _FAMILY_TOKENS:
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(tok) + r"(?![A-Za-z0-9])",
                     text or "", re.IGNORECASE):
            found.add(tok)
    return found


# ---------- CLI ----------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="strategy_metrics.py",
                                 description="strategy convergence four-metric snapshot")
    ap.add_argument("workspace", help="workspace root")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)
    snap = snapshot_for_workspace(Path(args.workspace))
    if args.json:
        print(json.dumps(snap, ensure_ascii=False, indent=2))
    else:
        for key, val in snap.items():
            print(f"{key}: {val}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
