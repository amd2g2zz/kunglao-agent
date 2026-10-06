#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rlvr/policy_compare.py — the offline policy comparison (issue #539 PR-2).

The ε-greedy control group (owner ruling 2026-10-06: a CONTROL, not a
product feature — no production sampling switch exists). This evaluator
answers ONE question over the logged trajectories: would a trivial
policy (uniform / ε-greedy over the same posterior means) have collected
more realized reward than the sampled Thompson choices did?

Estimator: SNIPS (self-normalized importance sampling) — the honest
small-N variant. With logged decisions (a_i chosen under behavior
propensity p_i, realized reward r_i):

    V̂_SNIPS(π) = Σ_i w_i·r_i / Σ_i w_i,   w_i = π(a_i | s_i) / p_i

π is read from the SAME evidence the behavior policy left: the envelope's
per-family candidate weights (the Thompson draw distribution at decision
time) give π_thompson; the greedy arm of ε-greedy takes the envelope's
argmax; uniform is 1/K. Rows without a propensity (pre-fix logs) are
skipped and counted — never silently imputed.

Small-sample honesty (the design doc §6 risk): below MIN_DECISIONS the
report carries `"verdict": "underpowered"` and no ranking — an ε-greedy
win at N=20 is noise dressed as a conclusion.

Usage:
    python scripts/rlvr/policy_compare.py <workspace> [--bootstrap 1000]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    # direct-path execution: the package parent (scripts/) is NOT on
    # sys.path (path[0] is scripts/rlvr/) — insert it before the sibling
    # imports (the q_cells direct-execution pattern)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rlvr.incremental_reward import read_transitions

MIN_DECISIONS = 40          # below this: underpowered, no verdict
DEFAULT_BOOTSTRAP = 1000
EPSILON = 0.1               # the control arm's exploration rate
POLICIES = ("thompson", "eps-greedy", "uniform")


def _audit_envelopes(ws: Path) -> list[dict]:
    """The dispatch-time envelopes from the audit stream: (claim, family,
    candidates{family: weight}, propensity)."""
    out: list[dict] = []
    p = Path(ws) / "runs" / "logs" / "e2e-audit.jsonl"
    if not p.is_file():
        return out
    for line in p.read_text(encoding="utf-8",
                            errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        det = row.get("detail")
        if isinstance(det, str):
            try:
                det = json.loads(det)
            except json.JSONDecodeError:
                continue
        if (row.get("event") or row.get("action")) != \
                "method_family_recorded" or not isinstance(det, dict):
            continue
        env = det.get("envelope") or {}
        fam = str(det.get("method_family") or env.get("family") or "")
        if not fam:
            continue
        cands = env.get("candidates") or {}
        out.append({
            "claim": str(row.get("claim") or ""),
            "family": fam,
            "weights": {str(k): float(v.get("weight", 0.0))
                        for k, v in cands.items()
                        if isinstance(v, dict)},
            "propensity": env.get("propensity"),
        })
    return out


def _pi(policy: str, family: str, weights: dict[str, float]) -> float:
    """π(a | s) under each comparison policy, read off the SAME envelope
    the behavior policy left (its candidate weights ARE the Thompson
    sampling distribution at decision time)."""
    if not weights:
        return 0.0
    if policy == "uniform":
        return 1.0 / len(weights)
    greedy = max(weights, key=weights.get)
    if policy == "eps-greedy":
        return (1.0 - EPSILON) * (1.0 if family == greedy else 0.0) \
            + EPSILON / len(weights)
    if policy == "thompson":
        total = sum(weights.values())
        return weights.get(family, 0.0) / total if total > 0 else 0.0
    raise ValueError(f"unknown policy {policy!r}")


def snips(decisions: list[dict], policy: str) -> dict:
    """SNIPS value estimate over the logged decisions + the effective
    sample size (Σw)²/Σw² — the diagnostics the small-N honesty needs."""
    ws: list[float] = []
    for d in decisions:
        p = float(d["propensity"])
        pa = _pi(policy, d["family"], d["weights"])
        if p > 0.0 and pa > 0.0:
            ws.append(pa / p)
    if not ws:
        return {"value": None, "ess": 0.0}
    s = sum(ws)
    ess = (s * s) / sum(w * w for w in ws)
    num = sum(w * d["reward"] for w, d in zip(ws, decisions))
    return {"value": num / s, "ess": ess}


def _bootstrap_ci(decisions: list[dict], policy: str, draws: int,
                  seed: int = 7) -> list[float]:
    rng = random.Random(seed)
    vals = []
    n = len(decisions)
    for _ in range(draws):
        sample = [decisions[rng.randrange(n)] for _ in range(n)]
        est = snips(sample, policy)
        if est["value"] is not None:
            vals.append(est["value"])
    if not vals:
        return [0.0, 0.0]
    vals.sort()
    return [vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]]


def compare(ws: Path, *, bootstrap: int = DEFAULT_BOOTSTRAP) -> dict:
    """The comparison report: per-policy SNIPS + CI + the verdict gate."""
    ws = Path(ws)
    transitions = read_transitions(ws)
    envelopes = _audit_envelopes(ws)
    by_key = {f"{e['claim']}|{e['family']}": e for e in envelopes}

    decisions: list[dict] = []
    skipped_no_propensity = 0
    for t in transitions:
        key = f"{t.get('dispatch_id')}|{t.get('a')}"
        env = by_key.get(key)
        if env is None or env.get("propensity") is None:
            skipped_no_propensity += 1
            continue
        decisions.append({
            "family": t.get("a"),
            "reward": (t.get("r_incr") or 0.0) + (t.get("r_settle") or 0.0),
            "weights": env["weights"],
            "propensity": env["propensity"],
        })

    report = {
        "schema": "policy-compare/1",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "workspace": str(ws),
        "decisions": len(decisions),
        "transitions": len(transitions),
        "skipped_no_propensity": skipped_no_propensity,
        "epsilon": EPSILON,
        "policies": {},
        "verdict": None,
    }
    if len(decisions) < MIN_DECISIONS:
        report["verdict"] = "underpowered"
        report["min_decisions"] = MIN_DECISIONS
        return report
    for pol in POLICIES:
        est = snips(decisions, pol)
        entry = {"snips": (round(est["value"], 6)
                           if est["value"] is not None else None),
                 "ess": round(est["ess"], 2)}
        if bootstrap and est["value"] is not None:
            lo, hi = _bootstrap_ci(decisions, pol, bootstrap)
            entry["ci95"] = [round(lo, 6), round(hi, 6)]
        report["policies"][pol] = entry
    ranked = sorted(
        ((p, v["snips"]) for p, v in report["policies"].items()
         if v["snips"] is not None),
        key=lambda kv: kv[1], reverse=True)
    report["verdict"] = ({"ranking": [p for p, _ in ranked],
                          "best": ranked[0][0] if ranked else None}
                         if ranked else "no-estimate")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="policy_compare.py",
        description="#539 PR-2: offline policy comparison (the ε-greedy "
                    "control group) over logged transitions + propensities")
    ap.add_argument("workspace")
    ap.add_argument("--bootstrap", type=int, default=DEFAULT_BOOTSTRAP)
    args = ap.parse_args(argv)
    print(json.dumps(compare(args.workspace,
                             bootstrap=args.bootstrap), indent=2))
    return 0


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())
