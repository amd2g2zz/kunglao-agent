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
skipped and counted — never silently imputed. 4-L8 discipline: rows
whose envelope carries ``declared: true`` are skipped and counted (π=1.0
by fiat — no draw receipt backs it, so the SNIPS mixing assumption does
not hold for them), and the two on-disk π carriers stamped from the same
receipt at the same dispatch — the audit envelope and the transition row
(via the launch stash) — are cross-checked; a disagreeing pair is
skipped, counted, and warned (a corrupted carrier can no longer move the
verdict silently).

Attribution discipline: every decision is cross-checked against each
sampler-attribution carrier present — the transition row, the audit
envelope and every q-cell dispatch record for that decision. A carrier
whose ``sampled_family`` names a different family than the logged arm,
with no explicit override marker, makes the (action, propensity) pair
incoherent — the decision is skipped, counted
(``skipped_family_mismatch``) and warned, never weighted. An earlier
incoherent dispatch for the same claim is not masked by a later coherent
one.

Small-sample honesty (the design doc §6 risk): below MIN_DECISIONS the
report carries `"verdict": "underpowered"` and no ranking — an ε-greedy
win at N=20 is noise dressed as a conclusion.

Usage:
    python scripts/rlvr/policy_compare.py <workspace> [--bootstrap 1000]
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
import random
import sys
from pathlib import Path

if __package__ in (None, ""):
    # direct-path execution: the package parent (scripts/) is NOT on
    # sys.path (path[0] is scripts/rlvr/) — insert it before the sibling
    # imports (the q_cells direct-execution pattern)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _common import utc_now_z
from kunglao_log import warn  # canonical warn: ONE implementation
from rlvr import q_cells as _qc
from rlvr.incremental_reward import read_transitions

MIN_DECISIONS = 40          # below this: underpowered, no verdict
DEFAULT_BOOTSTRAP = 1000
EPSILON = 0.1               # the control arm's exploration rate
POLICIES = ("thompson", "eps-greedy", "uniform")


class ControlledOPE:
    """Caller-supplied experimental design, never constructed from audit data.

    The caller must choose the seed independently before dispatch and keep
    the decision order and weights fixed before sampling. Replay checks
    consistency, not the truth of those randomization assumptions.
    """
    def __init__(self, *, seed: int, weights: dict, decision_ids: list[str]):
        if (not decision_ids or len(set(decision_ids)) != len(decision_ids)
                or not all(isinstance(x, str) and x for x in decision_ids)
                or not isinstance(weights, dict) or not weights
                or not all(isinstance(k, str) and k and isinstance(v, (float, int))
                           and math.isfinite(v) and v > 0 for k, v in weights.items())):
            raise ValueError("invalid controlled experiment design")
        self.seed = seed
        self.weights = dict(weights)
        self.decision_ids = tuple(decision_ids)

    def receipts(self):
        rng = random.Random(self.seed)
        names = sorted(self.weights)
        scale = max(self.weights.values())
        scaled = [self.weights[k] / scale for k in names]
        total = math.fsum(scaled)
        receipts = {}
        for decision_id in self.decision_ids:
            threshold = rng.random() * total
            cumulative = 0.0
            chosen = len(names) - 1
            for i, weight in enumerate(scaled):
                cumulative += weight
                if threshold < cumulative:
                    chosen = i
                    break
            receipts[decision_id] = {
                "family": names[chosen], "weights": dict(self.weights),
                "propensity": scaled[chosen] / total,
                "information_set": "fixed_observed_weights",
                "probability_source": "experiment_owned_rng"}
        return receipts


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
        cands = env.get("candidates")
        if not isinstance(cands, dict):
            cands = {}
        out.append({
            "claim": str(row.get("claim") or ""),
            "family": fam,
            "weights": {str(k): v.get("weight") if isinstance(v, dict) else None
                        for k, v in cands.items()},
            "propensity": env.get("propensity"),
            "probability_source": env.get("probability_source"),
            "information_set": env.get("information_set"),
            "declared": bool(env.get("declared")),
            "sampled_family": env.get("sampled_family"),
            "family_override": env.get("family_override"),
        })
    return out


def _qcell_attribution(ws: Path) -> dict[tuple[str, str], list[dict]]:
    """(claim, declared family) -> EVERY dispatch observation row for
    that decision — the q-cell substrate's sampler attribution history.
    A re-dispatch appends another row, so the index keeps them all: one
    incoherent dispatch must not be masked by a later coherent one.
    Empty on any read failure (the honest gap: the decision keeps its
    own carriers)."""
    out: dict[tuple[str, str], list[dict]] = {}
    try:
        for row in _qc.dispatch_rows(ws):
            claim = str(row.get("claim") or "").strip()
            fam = str(row.get("method_family") or "").strip()
            if claim and fam:
                out.setdefault((claim, fam), []).append(row)
    except Exception as exc:  # noqa: BLE001 — attribution is telemetry
        warn("policy_compare.attribution", f"{type(exc).__name__}: {exc}")
    return out


def _attribution_conflict(
        t: dict, env: dict,
        index: dict[tuple[str, str], list[dict]]) -> dict | None:
    """The first carrier whose (arm, sampler) pair is incoherent, or
    None when every carrier is coherent. Every sampler-attribution
    carrier present is consulted — the decision row, the audit envelope
    and every q-cell dispatch record for the decision — and one
    incoherent carrier is enough to refuse the decision."""
    family = str(t.get("a") or "")
    claim = str(t.get("claim_ref") or t.get("dispatch_id") or "")
    carriers = [
        {"method_family": family,
         "sampled_family": t.get("sampled_family"),
         "family_override": t.get("family_override")},
        {"method_family": family,
         "sampled_family": env.get("sampled_family"),
         "family_override": env.get("family_override")},
    ]
    carriers.extend(index.get((claim, family)) or ())
    for carrier in carriers:
        if not _qc.attribution_consistent(carrier):
            return carrier
    return None


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
        scale = max(weights.values())
        if scale <= 0:
            return 0.0
        total = math.fsum(w / scale for w in weights.values())
        return (weights.get(family, 0.0) / scale) / total
    raise ValueError(f"unknown policy {policy!r}")


def snips(decisions: list[dict], policy: str) -> dict:
    """SNIPS value estimate over the logged decisions + the effective
    sample size (Σw)²/Σw² — the diagnostics the small-N honesty needs."""
    if policy not in POLICIES:
        raise ValueError(f"unknown policy {policy!r}")
    weighted_rewards: list[tuple[float, float]] = []
    for d in decisions:
        try:
            p = float(d["propensity"])
            reward = float(d["reward"])
            weights = d["weights"]
            if (not math.isfinite(p) or not 0.0 < p <= 1.0
                    or not math.isfinite(reward)
                    or not isinstance(weights, dict)
                    or d["family"] not in weights
                    or not all(math.isfinite(float(w)) and float(w) >= 0
                               for w in weights.values())):
                continue
            pa = _pi(policy, d["family"], weights)
            if not math.isfinite(pa) or not 0.0 < pa <= 1.0:
                continue
            weight = pa / p
            if math.isfinite(weight):
                weighted_rewards.append((weight, reward))
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    if not weighted_rewards:
        return {"value": None, "ess": 0.0}
    scale = max(w for w, _ in weighted_rewards)
    normalized = [(w / scale, reward) for w, reward in weighted_rewards]
    s = sum(w for w, _ in normalized)
    ess = (s * s) / sum(w * w for w, _ in normalized)
    reward_scale = max(abs(reward) for _, reward in normalized)
    if reward_scale == 0:
        value = 0.0
    else:
        value = math.fsum((w / s) * (reward / reward_scale)
                          for w, reward in normalized) * reward_scale
    return {"value": value if math.isfinite(value) else None, "ess": ess}


def _bootstrap_ci(decisions: list[dict], policy: str, draws: int,
                  seed: int = 7) -> list[float] | None:
    rng = random.Random(seed)
    vals = []
    n = len(decisions)
    for _ in range(draws if n else 0):
        sample = [decisions[rng.randrange(n)] for _ in range(n)]
        est = snips(sample, policy)
        if est["value"] is not None:
            vals.append(est["value"])
    if not vals:
        return None
    vals.sort()
    return [vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]]


def _valid_support(weights, family):
    try:
        return (bool(weights) and str(family) in weights
                and all(math.isfinite(float(v)) and float(v) >= 0
                        for v in weights.values())
                and float(weights[str(family)]) > 0)
    except (TypeError, ValueError, OverflowError):
        return False


def _observed_reward(row):
    parts = [row[name] for name in ("r_incr", "r_settle") if name in row]
    if not parts:
        return None
    try:
        if not all(not isinstance(x, bool) and math.isfinite(float(x)) for x in parts):
            return None
        result = math.fsum(float(x) for x in parts)
    except (ValueError, TypeError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def compare(  # noqa: C901
        ws: Path, *, bootstrap: int = DEFAULT_BOOTSTRAP,
        experiment: ControlledOPE | None = None) -> dict:
    """The comparison report: per-policy SNIPS + CI + the verdict gate."""
    ws = Path(ws)
    transitions = read_transitions(ws)
    envelopes = _audit_envelopes(ws)
    by_key = {f"{e['claim']}|{e['family']}": e for e in envelopes}
    envelope_counts = Counter(f"{e['claim']}|{e['family']}" for e in envelopes)
    transition_counts = Counter(f"{t.get('dispatch_id')}|{t.get('a')}" for t in transitions)
    attribution = _qcell_attribution(ws)
    receipts = experiment.receipts() if isinstance(experiment, ControlledOPE) else {}
    audit_ids = Counter(str(e.get('claim') or '') for e in envelopes)
    transition_ids = Counter(str(t.get('dispatch_id') or '') for t in transitions)
    accepted_ids = set()

    decisions: list[dict] = []
    skipped_no_propensity = 0
    skipped_declared_fiat = 0
    skipped_propensity_mismatch = 0
    skipped_family_mismatch = 0
    skipped_ambiguous_dispatch = 0
    skipped_unknown_probability = 0
    skipped_invalid_probability = 0
    skipped_invalid_support = 0
    skipped_experiment_mismatch = 0
    skipped_invalid_reward = 0
    for t in transitions:
        key = f"{t.get('dispatch_id')}|{t.get('a')}"
        if envelope_counts[key] > 1 or transition_counts[key] > 1:
            skipped_ambiguous_dispatch += 1
            continue
        env = by_key.get(key)
        if env is None or env.get("propensity") is None:
            skipped_no_propensity += 1
            continue
        conflict = _attribution_conflict(t, env, attribution)
        if conflict is not None:
            # the row's sampler pair names another arm with no explicit
            # override marker: the logged action is not the action whose
            # probability is recorded, so it cannot be re-weighted.
            skipped_family_mismatch += 1
            warn("policy_compare.compare",
                 f"refused decision {key!r}: sampled_family "
                 f"{conflict.get('sampled_family')!r} != arm family "
                 f"{str(t.get('a') or '')!r} with no explicit override — "
                 f"excluded from off-policy weighting")
            continue
        if env.get("declared"):
            # 4-L8: declared selection rode π=1.0 by fiat — no draw
            # receipt backs it, so the SNIPS mixing assumption does not
            # hold; the row leaves the weighted join, counted.
            skipped_declared_fiat += 1
            continue
        try:
            propensity = float(env["propensity"])
            t_prop = t.get("propensity")
            actual = float(t_prop) if t_prop is not None else None
        except (TypeError, ValueError, OverflowError):
            skipped_invalid_probability += 1
            continue
        if (not math.isfinite(propensity) or not 0 < propensity <= 1
                or actual is not None and (not math.isfinite(actual) or not 0 < actual <= 1)):
            skipped_invalid_probability += 1
            continue
        if not _valid_support(env["weights"], t.get("a")):
            skipped_invalid_support += 1
            continue
        if actual is not None and abs(actual - propensity) > 1e-9:
            skipped_propensity_mismatch += 1
            warn("policy_compare.compare",
                 f"refused decision {key!r}: propensity carriers disagree")
            continue
        expected = receipts.get(str(t.get('dispatch_id') or ''))
        if expected is None:
            skipped_unknown_probability += 1
            continue
        if (any(env.get(field) != expected[field] for field in
                ('family', 'weights', 'propensity', 'information_set', 'probability_source'))
                or t.get('a') != expected['family'] or t_prop is None
                or env.get('family_override') or t.get('family_override')):
            skipped_experiment_mismatch += 1
            continue
        reward = _observed_reward(t)
        if reward is None:
            skipped_invalid_reward += 1
            continue
        decisions.append({'family': expected['family'], 'weights': expected['weights'],
                          'propensity': expected['propensity'], 'reward': reward})
        accepted_ids.add(str(t.get('dispatch_id') or ''))

    report = {
        "schema": "policy-compare/1",
        "ts": utc_now_z(),
        "workspace": str(ws),
        "decisions": len(decisions),
        "transitions": len(transitions),
        "skipped_no_propensity": skipped_no_propensity,
        "skipped_declared_fiat": skipped_declared_fiat,
        "skipped_propensity_mismatch": skipped_propensity_mismatch,
        "skipped_family_mismatch": skipped_family_mismatch,
        "skipped_ambiguous_dispatch": skipped_ambiguous_dispatch,
        "skipped_unknown_probability": skipped_unknown_probability,
        "skipped_invalid_probability": skipped_invalid_probability,
        "skipped_invalid_support": skipped_invalid_support,
        "skipped_experiment_mismatch": skipped_experiment_mismatch,
        "skipped_invalid_reward": skipped_invalid_reward,
        "epsilon": EPSILON,
        "policies": {},
        "verdict": None,
    }
    if experiment is not None:
        planned = set(receipts)
        integrity = {
            'missing_audit': sum(audit_ids[key] == 0 for key in planned),
            'missing_transition': sum(transition_ids[key] == 0 for key in planned),
            'duplicate_audit': sum(audit_ids[key] > 1 for key in planned),
            'duplicate_transition': sum(transition_ids[key] > 1 for key in planned),
            'unexpected_audit': sum(count for key, count in audit_ids.items()
                                    if key not in planned),
            'unexpected_transition': sum(count for key, count in transition_ids.items()
                                         if key not in planned),
            'rejected_planned': len(planned - accepted_ids),
        }
        report['experiment_integrity'] = integrity
        if any(integrity.values()):
            report['verdict'] = 'incomplete_experiment'
            return report
    if len(decisions) < MIN_DECISIONS:
        report["verdict"] = "underpowered"
        report["min_decisions"] = MIN_DECISIONS
        return report
    missing_interval = False
    insufficient_overlap = False
    for pol in POLICIES:
        est = snips(decisions, pol)
        entry = {"snips": (round(est["value"], 6)
                           if est["value"] is not None else None),
                 "ess": round(est["ess"], 2)}
        if est['value'] is None or est['ess'] < 20 or est['ess'] / len(decisions) < 0.2:
            insufficient_overlap = True
        if bootstrap and est["value"] is not None:
            interval = _bootstrap_ci(decisions, pol, bootstrap)
            entry["ci95"] = ([round(value, 6) for value in interval]
                             if interval is not None else None)
            missing_interval |= interval is None
        report["policies"][pol] = entry
    if missing_interval:
        report["verdict"] = "underpowered"
        return report
    if insufficient_overlap:
        report['verdict'] = 'insufficient_overlap'
        return report
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
