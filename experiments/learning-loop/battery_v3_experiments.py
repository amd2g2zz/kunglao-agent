# -*- coding: utf-8 -*-
"""battery_v3_experiments.py — the #887 battery's TWO NEW experiments.

Both ride the v3 simulator's real-face rollouts (loop_sim_v3) — these
are the measurement harnesses, not new policy:

  run_termination_comparison  NEW-A: β termination vs a fixed step
          count on J(φ) = E[R_task − λ·C_total]. Both arms run the SAME
          scenario with the assignment PINNED to one family (the real
          assigner face, single-candidate draw) — J then measures the
          TERMINATION axis alone: the β arm stops on question-covered /
          loss-cut; the fixed arm always spends its step count.
  run_portfolio_coverage      NEW-B: action-space evidence coverage —
          the leader+2-probe portfolio banks evidence for all THREE
          method families per dispatch through policy.prober's
          potential-based rails; the single-select arm banks one.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

_LOOP = Path(__file__).resolve().parent
_SCRIPTS = _LOOP.parents[1] / "scripts"
for _p in (_LOOP, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import loop_sim  # noqa: E402 — the shared workspace bootstrap
from core import Budget  # noqa: E402
from policy import prober  # noqa: E402
from rlvr import q_cells  # noqa: E402

from loop_sim_v3 import (FAMILIES,  # noqa: E402
                         FIXED_STEPS, GAMMA, LAMBDA_COST,
                         PER_DISPATCH_BUDGET_S, TERMINAL_BONUS, TRACKED,
                         _assign, _seed_ctx, _true_family, run_rollout,
                         settle_one_dispatch, situation_signature)



#: NEW-A scope note (review): the fixed arm's N is the documented
#: cold-prior default (4). At N<=2 the fixed arm wins DEAD tasks on
#: cost (0.8 vs the loss-cut's 1.2) — the J-dominance claim is scoped
#: to "the documented cold-prior deadline", not to every fixed N.
def run_termination_comparison(root, *, seeds: int = 8,
                               fixed_steps: int = FIXED_STEPS,
                               lam: float = LAMBDA_COST,
                               gamma: float = GAMMA) -> dict:
    """NEW-A: β termination vs a fixed step count on
    J(φ) = E[R_task − λ·C_total]. Per seed a 4-task scenario runs
    TWICE — once under the terminator's rules (loss-cut + question-
    covered, watchdog armed), once under the fixed step count that
    ignores them. R_task = TERMINAL_BONUS when the question is covered
    else 0; C_total = the rollout's own token bill. Slot 0 is always
    answerable (the efficiency credit is exercised on every seed); the
    rest draw answerable/dead deterministically from the seed."""
    root = Path(root)
    per_seed: list[dict] = []
    arms0: dict[str, dict] = {}
    for seed in range(seeds):
        plan = [("a0", "offsets")]
        rng = random.Random(f"v3/na/{seed}")
        for i in range(1, 4):
            situation = "offsets" if rng.random() < 0.5 else f"dead-{i}"
            plan.append((f"t{i}", situation))
        arms: dict[str, dict] = {}
        for arm, fixed in (("beta", None), ("fixed", fixed_steps)):
            ws = root / f"{arm}-{seed}"
            ws.mkdir(parents=True, exist_ok=True)
            loop_sim._bootstrap(ws)
            ctx = _seed_ctx(ws, seed=seed, lap=1, gamma=gamma)
            rollouts = []
            for tid, situation in plan:
                rollout = run_rollout(
                    ws, ctx, rid=f"ro-{tid}", task_id=tid,
                    situation=situation, gamma=gamma, ablate_credit=False,
                    scramble_credit=False, ablate_selector=False,
                    fixed_steps=fixed,
                    pinned_family=_true_family(situation) or TRACKED)
                rollouts.append(rollout)
            reward = [TERMINAL_BONUS if r["covered"] else 0.0
                      for r in rollouts]
            cost = [r["cost"] for r in rollouts]
            j_values = [rw - lam * c for rw, c in zip(reward, cost)]
            arms[arm] = {
                "J": sum(j_values) / len(j_values),
                "success": sum(1 for r in rollouts if r["covered"])
                / len(rollouts),
                "mean_steps": sum(r["steps"] for r in rollouts)
                / len(rollouts),
                "mean_reward": sum(reward) / len(reward),
                "mean_cost": sum(cost) / len(cost),
                "efficiency_credits": sum(1 for r in rollouts
                                          if r["efficiency_credit"]),
            }
        per_seed.append({
            "seed": seed,
            "beta_J": arms["beta"]["J"], "fixed_J": arms["fixed"]["J"],
            "beta_success": arms["beta"]["success"],
            "fixed_success": arms["fixed"]["success"],
            "beta_steps": arms["beta"]["mean_steps"],
            "fixed_steps_mean": arms["fixed"]["mean_steps"],
        })
        if seed == 0:
            arms0 = arms
    return {
        "seeds": seeds, "fixed_steps": fixed_steps, "lam": lam,
        "per_seed": per_seed,
        "beta": arms0["beta"], "fixed": arms0["fixed"],
    }


def run_portfolio_coverage(root, *, dispatches: int = 4,
                           situation: str = "offsets",
                           gamma: float = GAMMA) -> dict:
    """NEW-B: action-space evidence coverage. The portfolio arm runs
    ``dispatches`` leader+2-probe plans (the leader executes through
    the real settle path; each probe lands its three-row evidence
    through policy.prober); the single-select arm runs the same budget
    as one assigner draw + dispatch per round. Coverage = banked
    evidence per family, counted from the ONE ledger."""
    root = Path(root)
    sig = situation_signature(situation)
    probe_candidates = [f for f in FAMILIES if f != TRACKED]
    budget = Budget(wall_s=PER_DISPATCH_BUDGET_S)

    def _banked_rows(ws) -> dict[str, int]:
        counts = {f: 0 for f in FAMILIES}
        for row in q_cells.trajectory_rows(ws):
            if row.get("schema") != q_cells.OBS_SCHEMA:
                continue
            if row.get("credit") is None:
                continue
            fam = q_cells.family_of_action(str(row.get("arm_key") or ""))
            if fam in counts:
                counts[fam] += 1
        return counts

    # --- the portfolio arm
    ws_p = root / "portfolio"
    ws_p.mkdir(parents=True, exist_ok=True)
    loop_sim._bootstrap(ws_p)
    ctx = _seed_ctx(ws_p, seed=0, lap=1, gamma=gamma)
    probe_credits: list[float] = []
    leader_success = 0.0
    coverage_after_1_p = 0
    for k in range(1, dispatches + 1):
        plan = prober.plan_portfolio(ws_p, TRACKED, probe_candidates,
                                     signature_hash=sig, budget=budget)
        settled = settle_one_dispatch(ws_p, situation, TRACKED,
                                      rollout=f"ro-p-{k}", gamma=gamma)
        leader_success += settled["credit"] or 0.0
        # the mock comparison: neither probe answers the tracked
        # situation; ranks follow the documented sorted-arm tiebreak.
        # Distinct step ids per probe — the record face's idempotence
        # identity is (rollout_id, step_id)
        for rank, probe_family in enumerate(sorted(probe_candidates),
                                             start=2):
            landed = prober.record_probe(
                ws_p, plan, probe_family, rollout_id=f"ro-p-{k}",
                step_id=f"s{k}-probe-{rank}", rank=rank, verified=False,
                verdict="no-answer",
                summary=f"probe rank={rank}/3 vs leader={TRACKED}",
                ts=ctx["clock"].tick())
            probe_credits.append(landed["credit"])
        if k == 1:
            coverage_after_1_p = sum(1 for c in _banked_rows(ws_p).values()
                                     if c > 0)
    counts_p = _banked_rows(ws_p)
    pending_results = sum(
        1 for row in q_cells.trajectory_rows(ws_p)
        if row.get("schema") == q_cells.SCHEMA_RESULT_V2
        and str(row.get("rollout_id") or "").startswith("ro-p-")
        and "probe" in str(row.get("step_id") or "")
        and row.get("r_t") is None)
    fold_p = q_cells.fold(q_cells.default_store(ws_p), gamma=gamma)
    portfolio = {
        "rows_per_family": counts_p,
        "coverage_after_1": coverage_after_1_p,
        "total_banked": sum(counts_p.values()),
        "min_family_rows": min(counts_p.values()),
        "families_with_mass": sum(1 for f in FAMILIES
                                  if any(m > 0 for m in
                                         fold_p.family_mass(f))),
        "probe_credits": probe_credits,
        "probe_pending_results": pending_results,
        "leader_settled_success": leader_success,
    }

    # --- the single-select arm
    ws_s = root / "single"
    ws_s.mkdir(parents=True, exist_ok=True)
    loop_sim._bootstrap(ws_s)
    ctx_s = _seed_ctx(ws_s, seed=0, lap=1, gamma=gamma)
    coverage_after_1_s = 0
    for k in range(1, dispatches + 1):
        receipt = _assign(ws_s, ctx_s, f"ro-s-{k}", sig, k, list(FAMILIES))
        settle_one_dispatch(ws_s, situation, receipt["family"],
                            rollout=f"ro-s-{k}", gamma=gamma)
        if k == 1:
            coverage_after_1_s = sum(1 for c in _banked_rows(ws_s).values()
                                     if c > 0)
    counts_s = _banked_rows(ws_s)
    fold_s = q_cells.fold(q_cells.default_store(ws_s), gamma=gamma)
    single = {
        "rows_per_family": counts_s,
        "coverage_after_1": coverage_after_1_s,
        "total_banked": sum(counts_s.values()),
        "min_family_rows": min(counts_s.values()),
        "families_with_mass": sum(1 for f in FAMILIES
                                  if any(m > 0 for m in
                                         fold_s.family_mass(f))),
    }
    return {"dispatches": dispatches, "portfolio": portfolio,
            "single": single}
