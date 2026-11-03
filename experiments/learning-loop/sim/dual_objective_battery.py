# -*- coding: utf-8 -*-
"""dual_objective_battery.py — the #951 five-config battery.

Drives the dual-objective world (dual_objective_world) through the
FIVE mechanism configs of issue #951 and renders the result set in the
proof battery's conclusion format (the test_proof_battery_v3 style:
fixed seeds, per-batch strict ordering, pooled 3-sd margins, verdicts
derived — never vibes).

  config 1  baseline       DTS + #932 measured-potential ladder credit.
                           PREDICTION: collapses onto the leak arm. If
                           it does NOT, the diagnosis is falsified and
                           the direction-layer card is cancelled — the
                           finding would be recorded, never tuned away.
  config 2  dense-floor    the resurrected 0.3 unverified anchor, flat
                           per step regardless of face (the #930
                           6.0-vs-0.6 adversarial-pleasing shape).
  config 3  +direction-PRM the oracle-weighted direction-contribution
                           judge (signal-SHAPE measurement; production
                           would have to learn the judge).
  config 4  +racing elim.  Thompson over directions where a direction
                           may be abandoned ONLY on posterior collapse
                           (the anti-premature-surrender leg).
  config 5  3 + 4          the combined mechanism.

METRICS (per config; mean ± spread over fixed-seed batches):
  (a) leak-collapse       rollouts spending the MAJORITY of their steps
                          on the leak arm
  (b) premature-surrender rollouts that dropped the true-solve
                          direction at a boundary while its posterior
                          had NOT collapsed AND never ran it again —
                          a SURRENDER, not churn (a transient departure
                          that returns is exploration; the metric keys
                          on the rollout's direction of record dying
                          while the arm was still raceable)
  (c) completion          rollouts reaching the primary objective
                          (all 8 ladder rungs PROVEN) — plus the
                          adversarial-economics axis (credit and cost
                          per rollout; the #930 shape).

PASS CRITERIA (BOTH, per mechanism — configs 3/4/5 vs config 1):
  1. (a) significantly LOWER than config 1 (pooled 3-sd margin AND
     every batch orders the same way — the battery's per-seed
     discipline);
  2. (b) NOT raised vs config 1.
A mechanism failing either criterion is marked NOT-for-production.

Determinism: fixed seeds end to end (seed0 threads every rollout).
Nothing here changes production wiring — the whole tier stays in the
declared sim package (#936).
"""
from __future__ import annotations

import sys
from pathlib import Path

_SIM = Path(__file__).resolve().parent
_LOOP = _SIM.parent
_SCRIPTS = _SIM.parents[2] / "scripts"
for _p in (_SIM, _LOOP, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from dual_objective_world import (LEAK,  # noqa: E402
                                  Mechanisms, PRIMARY, run_config)

#: the five configs, in the issue's order — (name, mechanisms)
CONFIGS: tuple[tuple[str, Mechanisms], ...] = (
    ("1-baseline", Mechanisms()),
    ("2-dense-floor", Mechanisms(dense_floor=True)),
    ("3-direction-prm", Mechanisms(direction_prm=True)),
    ("4-racing-elim", Mechanisms(racing=True)),
    ("5-prm-racing", Mechanisms(direction_prm=True, racing=True)),
)

#: the verdict vocabulary (the battery's conclusion format)
VERDICT_PASS = "PASS"
VERDICT_NOT_FOR_PRODUCTION = "NOT-for-production"


# ------------------------------------------------------------------ metrics

def premature_surrender(receipt: dict) -> bool:
    """Metric (b)'s event predicate: the rollout dropped the true-solve
    direction at a boundary while its posterior had NOT collapsed, and
    NEVER ran it again — the direction of record died while the arm was
    still raceable. A transient departure that RETURNS to true-solve is
    churn (exploration), not surrender, and does not count."""
    last_primary = -1
    for entry in receipt["stretch_trace"]:
        if entry["arm"] == PRIMARY:
            last_primary = entry["boundary"]
    return any(e["boundary"] > last_primary
               for e in receipt["premature_abandons"])


def config_metrics(receipts: list[dict]) -> dict:
    """The three issue metrics + the adversarial-economics axis, over
    one config's rollout receipts."""
    n = len(receipts)
    if n == 0:
        raise ValueError("config_metrics: no receipts")
    leak = sum(1 for r in receipts
               if 2 * r["steps_by_arm"][LEAK] > r["steps_total"])
    surrender = sum(1 for r in receipts if premature_surrender(r))
    completed = sum(1 for r in receipts if r["terminal"] == "completed")
    return {"n": n,
            "leak_collapse": leak / n,
            "premature_surrender": surrender / n,
            "completion": completed / n,
            "credit_per_rollout": sum(r["credit_total"]
                                      for r in receipts) / n,
            "cost_per_rollout": sum(r["cost_total"]
                                    for r in receipts) / n}



def _margin3(p1: float, p2: float, n1: int, n2: int) -> float:
    """The 3-sd pooled margin between two Bernoulli rates (the battery's
    sampled-claim discipline: a claim needs >= 3 sd of separation)."""
    var = (p1 * (1.0 - p1) / n1) + (p2 * (1.0 - p2) / n2)
    return 3.0 * var ** 0.5


# ------------------------------------------------------------------ battery

def run_five_configs(root, *, batches: int = 4, rollouts: int = 50,
                     seed0: int = 951) -> dict:
    """Run all five configs, ``batches`` fixed-seed batches of
    ``rollouts`` fresh-workspace rollouts each. Returns the full
    per-batch metrics plus the pooled view the conclusions ride.
    The battery OWNS its root: any previous run's workspaces under it
    are removed first (stale ledger rows would silently join the fold
    reads — the exact failure mode the freshness discipline exists
    for)."""
    import shutil

    root = Path(root)
    if root.exists():
        shutil.rmtree(root)
    results: dict[str, dict] = {}
    for name, mech in CONFIGS:
        batch_rows = []
        receipts = []
        for b in range(batches):
            out = run_config(root / f"b{b}", name=name, mech=mech,
                             rollouts=rollouts, seed=seed0 + b)
            receipts.extend(out["receipts"])
            batch_rows.append(config_metrics(out["receipts"]))
        pooled = config_metrics(receipts)
        results[name] = {
            "mech": mech, "batches": batches, "rollouts": rollouts,
            "batch_metrics": batch_rows, "pooled": pooled,
            "seeds": [f"{seed0 + b}/{name}" for b in range(batches)],
        }
    return {"root": str(root), "seed0": seed0, "batches": batches,
            "rollouts": rollouts, "configs": results}


# --------------------------------------------------------------- conclusions


def _every_batch_lower(results: dict, name: str, base: str,
                       key: str) -> bool:
    cfgs = results["configs"]
    return all(b[key] < s[key]
               for b, s in zip(cfgs[name]["batch_metrics"],
                               cfgs[base]["batch_metrics"]))


def conclusions(results: dict) -> dict:
    """The battery's verdict set — every conclusion asserted-by-number,
    in the proof battery's format."""
    cfgs = results["configs"]
    base = "1-baseline"
    c1 = cfgs[base]["pooled"]
    n1 = int(c1["n"])
    out: dict[str, dict] = {}

    out["config1_collapse_reproduced"] = {
        "verdict": c1["leak_collapse"] >= 0.4,
        "leak_collapse": c1["leak_collapse"],
        "note": ("baseline collapses onto the leak arm — the in-silico "
                 "reproduction of P8 round-1" if c1["leak_collapse"] >= 0.4
                 else "BASELINE DID NOT REPRODUCE THE COLLAPSE — the "
                      "diagnosis is falsified; the direction-layer card "
                      "is cancelled (recorded, not tuned away)")}

    floor = cfgs["2-dense-floor"]["pooled"]
    mech_min_completion = min(cfgs[n]["pooled"]["completion"]
                              for n in ("3-direction-prm", "4-racing-elim",
                                        "5-prm-racing"))
    out["config2_negative_control"] = {
        "verdict_worse_on_surrender":
            floor["premature_surrender"] > c1["premature_surrender"],
        "verdict_completion_below_every_mechanism":
            floor["completion"] < mech_min_completion,
        "leak_collapse": floor["leak_collapse"],
        "premature_surrender": floor["premature_surrender"],
        "completion": floor["completion"],
        "note": ("the flat floor destroys the GRADIENT: every arm is "
                 "priced identical (0.3/step), so the leak arm loses its "
                 "hijack pull (near-uniform wandering) while the "
                 "direction choice becomes a coin toss — no gradient to "
                 "find the primary objective with")}

    for name in ("3-direction-prm", "4-racing-elim", "5-prm-racing"):
        pooled = cfgs[name]["pooled"]
        n2 = int(pooled["n"])
        drop_a = c1["leak_collapse"] - pooled["leak_collapse"]
        crit1 = (drop_a > _margin3(c1["leak_collapse"],
                                   pooled["leak_collapse"], n1, n2)
                 and _every_batch_lower(results, name, base,
                                        "leak_collapse"))
        raise_b = (pooled["premature_surrender"]
                   > c1["premature_surrender"]
                   + _margin3(pooled["premature_surrender"],
                              c1["premature_surrender"], n2, n1))
        out[name] = {
            "verdict": (VERDICT_PASS if (crit1 and not raise_b)
                        else VERDICT_NOT_FOR_PRODUCTION),
            "criterion1_leak_drop_significant": crit1,
            "criterion2_surrender_not_raised": not raise_b,
            "leak_collapse": pooled["leak_collapse"],
            "premature_surrender": pooled["premature_surrender"],
            "completion": pooled["completion"],
            "leak_drop": round(drop_a, 6),
            "margin3": round(_margin3(c1["leak_collapse"],
                                      pooled["leak_collapse"], n1, n2), 6),
        }
    return out


# --------------------------------------------------------------- rendering

def render_table(results: dict) -> str:
    """The human-readable results table (the run output's face)."""
    lines = []
    ap = lines.append
    ap("#951 dual-objective sim world — five-config results")
    ap(f"seeds: seed0={results['seed0']} fixed; "
       f"{results['batches']} batches x {results['rollouts']} "
       f"rollouts per config (fresh workspace per rollout)")
    ap("")
    header = (f"{'config':<18}{'leak-collapse':>15}{'surrender':>12}"
              f"{'completion':>13}{'credit/ro':>11}{'cost/ro':>9}")
    ap(header)
    ap("-" * len(header))
    for name, _mech in CONFIGS:
        row = results["configs"][name]["pooled"]
        batches = results["configs"][name]["batch_metrics"]
        spreads = {k: (max(bb[k] for bb in batches), min(bb[k]
                                                          for bb in batches))
                   for k in ("leak_collapse", "premature_surrender",
                             "completion")}
        ap(f"{name:<18}"
           f"{row['leak_collapse']:>9.3f} "
           f"[{spreads['leak_collapse'][1]:.2f}-"
           f"{spreads['leak_collapse'][0]:.2f}]"
           f"{row['premature_surrender']:>7.3f} "
           f"[{spreads['premature_surrender'][1]:.2f}-"
           f"{spreads['premature_surrender'][0]:.2f}]"
           f"{row['completion']:>8.3f} "
           f"[{spreads['completion'][1]:.2f}-{spreads['completion'][0]:.2f}]"
           f"{row['credit_per_rollout']:>11.2f}"
           f"{row['cost_per_rollout']:>9.1f}")
    ap("")
    ap("verdicts:")
    conc = conclusions(results)
    c1 = conc["config1_collapse_reproduced"]
    ap(f"  config 1 collapse reproduced: "
       f"{'YES' if c1['verdict'] else 'NO — DIAGNOSIS FALSIFIED'} "
       f"(leak-collapse {c1['leak_collapse']:.3f})")
    c2 = conc["config2_negative_control"]
    base_surrender = results["configs"]["1-baseline"]["pooled"][
        "premature_surrender"]
    ap(f"  config 2 control (0.3 flat floor): gradient destroyed — "
       f"leak-collapse {c2['leak_collapse']:.3f} (the hijack pull is "
       f"GONE, not worsened), surrender "
       f"{c2['premature_surrender']:.3f} vs baseline "
       f"{base_surrender:.3f} "
       f"(worse: {c2['verdict_worse_on_surrender']}), "
       f"completion {c2['completion']:.3f} below every mechanism: "
       f"{c2['verdict_completion_below_every_mechanism']}")
    for name in ("3-direction-prm", "4-racing-elim", "5-prm-racing"):
        row = conc[name]
        ap(f"  {name}: {row['verdict']} "
           f"(leak {row['leak_collapse']:.3f} vs "
           f"{results['configs']['1-baseline']['pooled']['leak_collapse']:.3f}, "
           f"drop {row['leak_drop']:.3f} > 3sd {row['margin3']:.3f}: "
           f"{row['criterion1_leak_drop_significant']}; "
           f"surrender not raised: "
           f"{row['criterion2_surrender_not_raised']})")
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover — the run face
    import tempfile
    _root = Path(tempfile.gettempdir()) / "v951-battery"
    _out = run_five_configs(_root)
    print(render_table(_out))
