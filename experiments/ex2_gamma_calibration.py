# -*- coding: utf-8 -*-
"""ex2_gamma_calibration.py — EX-2: γ schedule calibration replay (#428).

DECLARED SYNTHETIC (plan W2-T1 risk row: γ calibration has no real
drift data yet). A 4-arm posterior bank runs a Thompson loop for T=600
rounds across 25 seeds; one arm's true Bernoulli rate FLIPS mid-stream
(0.8 → 0.2 at t=300). Candidate γ schedules — the constant grid
{0.9, 0.95, 0.98, 0.99, 1.0} plus a declared grid of outcome-adaptive
(floors × EMA λ) — replay the same seeded streams; we measure:

  - tracking error: mean |decayed_mean(t) − true_p(t)| on the flip arm,
    pre-flip window [100, 300) and post-flip window [300, 600) (stale
    unplayed rounds count — that staleness is what the selector sees);
  - regret: cumulative best_true_p(t) − p(played);
  - cold-start width: mean posterior width of the flip arm over the
    first 50 rounds.

The engine loop maintains the decayed counts incrementally with the
SHIPPED recurrence ((α, β) ← γ·(α, β) + obs, priors seeded at birth);
a bit-equality anchor replays a prefix through rlvr.posteriors.fold()
from a real store run to prove sim == shipped math.

Output: the numbers table + chosen default → experiments/ex2-gamma-
calibration.md. Reproduce: uv run --project . python
experiments/ex2_gamma_calibration.py
"""
from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from rlvr import posteriors as rp  # noqa: E402

T = 600
FLIP_AT = 300
P_WARMUP = 100          # pre-flip error window starts here
WIDTH_WINDOW = 50       # cold-start width window
SEEDS = list(range(25))

ARM_STATIC_HI = "arm-static-hi"    # p = 0.70
ARM_FLIP = "arm-flip"              # p = 0.80 -> 0.20 at FLIP_AT
ARM_STATIC_MID = "arm-static-mid"  # p = 0.50
ARM_STATIC_LO = "arm-static-lo"    # p = 0.35
ARMS = (ARM_STATIC_HI, ARM_FLIP, ARM_STATIC_MID, ARM_STATIC_LO)
STATE = "sig-ex2"

CONSTANT_GRID = (0.9, 0.95, 0.98, 0.99, 1.0)
ADAPTIVE_GRID = tuple((floor, lam)
                      for floor in (0.8, 0.9)
                      for lam in (0.9, 0.95, 0.98))


def true_p(arm: str, t: int) -> float:
    if arm == ARM_STATIC_HI:
        return 0.70
    if arm == ARM_FLIP:
        return 0.80 if t < FLIP_AT else 0.20
    if arm == ARM_STATIC_MID:
        return 0.50
    return 0.35


class CellState:
    """One cell's decayed counts — the shipped recurrence, incremental."""

    __slots__ = ("alpha", "beta", "n_eff")

    def __init__(self):
        self.alpha = rp.PRIOR_ALPHA_DEFAULT
        self.beta = rp.PRIOR_BETA_DEFAULT
        self.n_eff = 0.0

    def observe(self, outcome: int, gamma: float) -> None:
        self.alpha = gamma * self.alpha + float(outcome)
        self.beta = gamma * self.beta + float(1 - outcome)
        self.n_eff = gamma * self.n_eff + 1.0

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def width(self) -> float:
        a, b = self.alpha, self.beta
        total = a + b
        return math.sqrt(a * b / (total * total * (total + 1.0)))


def run_seed(seed: int, schedule_factory) -> dict:
    """One Thompson loop. The schedule drives BOTH the γ applied at each
    observation and (for the adaptive forms) its own outcome state."""
    rng = random.Random(seed)
    schedule = schedule_factory()
    cells = {arm: CellState() for arm in ARMS}
    pre_err = post_err = pre_n = post_n = 0
    width_sum = width_n = 0
    regret = 0.0
    for t in range(T):
        draws = {arm: rng.betavariate(cells[arm].alpha, cells[arm].beta)
                 for arm in ARMS}
        played = max(ARMS, key=lambda a: draws[a])
        if t < WIDTH_WINDOW:
            width_sum += cells[ARM_FLIP].width
            width_n += 1
        p_played = true_p(played, t)
        regret += max(true_p(a, t) for a in ARMS) - p_played
        outcome = 1 if rng.random() < p_played else 0
        # γ in force for THIS observation = schedule's judgment from the
        # past (no peeking), matching fold()'s schedule replay order.
        gamma = schedule.gamma()
        schedule.observe(outcome)
        cells[played].observe(outcome, gamma)
        err = abs(cells[ARM_FLIP].mean - true_p(ARM_FLIP, t))
        if P_WARMUP <= t < FLIP_AT:
            pre_err += err
            pre_n += 1
        elif t >= FLIP_AT:
            post_err += err
            post_n += 1
    return {"pre_err": pre_err / pre_n, "post_err": post_err / post_n,
            "regret": regret, "cold_width": width_sum / width_n}


def _anchor_bit_equality(tmp: Path) -> None:
    """Sim == shipped math: replay 60 rounds of seed-0 γ=0.95 through a
    REAL store + rlvr.posteriors.fold and require bit-equality with the
    incremental sim state."""
    ws = tmp / "anchor"
    sim = CellState()
    rng_sim = random.Random(0)
    outcomes = []
    for _ in range(60):
        outcome = 1 if rng_sim.random() < 0.8 else 0
        outcomes.append(outcome)
        sim.observe(outcome, 0.95)
        assert rp.record(ws, STATE, ARM_FLIP, outcome, gamma=0.95)["appended"]
    shipped = rp.fold(ws).cell(STATE, ARM_FLIP)
    assert shipped["alpha"].hex() == sim.alpha.hex(), "sim/shipped drift (alpha)"
    assert shipped["beta"].hex() == sim.beta.hex(), "sim/shipped drift (beta)"
    assert shipped["n_effective"].hex() == sim.n_eff.hex(), "sim/shipped n_eff"


def _stats(values: list[float]) -> tuple[float, float]:
    n = len(values)
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return mean, math.sqrt(var)


def main() -> int:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        _anchor_bit_equality(Path(td))
    print("anchor: sim == rlvr.posteriors.fold bit-exact on a 60-round "
          "store replay")

    candidates: list[tuple[str, object]] = [
        (f"constant γ={g}", (lambda g=g: rp.gamma_constant(g)))
        for g in CONSTANT_GRID]
    candidates += [
        (f"adaptive floor={f} λ={l}",
         (lambda f=f, l=l: rp.OutcomeAdaptiveGamma(gamma_floor=f,
                                                   ema_lambda=l)))
        for f, l in ADAPTIVE_GRID]

    rows = []
    for name, factory in candidates:
        runs = [run_seed(seed, factory) for seed in SEEDS]
        row = {"candidate": name}
        for metric in ("pre_err", "post_err", "regret", "cold_width"):
            mean, sd = _stats([r[metric] for r in runs])
            row[metric] = round(mean, 4)
            row[f"{metric}_sd"] = round(sd, 4)
        rows.append(row)

    print(json.dumps(rows, indent=2))
    out = ROOT / "experiments" / "ex2-results.json"
    out.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    print(f"saved {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
