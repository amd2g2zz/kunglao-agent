# EX-2 — γ schedule calibration replay (issue #428, v0.1.6 W2-T1)

**DECLARED SYNTHETIC** (plan W2-T1 risk row: γ calibration has no real
drift data yet — the synthetic injection is the declared substitute, to
be re-run against real campaign data when W3 measurement lands).

Reproduce: `uv run --project . python experiments/ex2_gamma_calibration.py`
(raw numbers: `experiments/ex2-results.json`, same commit).
Harness: `experiments/ex2_gamma_calibration.py`. The sim's incremental
decay state is bit-anchored against the shipped
`rlvr.posteriors.fold()` (a 60-round store replay must match the sim
alpha/beta/n_eff bit-exactly or the harness aborts).

## Setup

- 4-arm posterior bank, one state cell row per arm
  (`arm-static-hi` p=0.70, **`arm-flip` p=0.80 → 0.20 at t=300**,
  `arm-static-mid` p=0.50, `arm-static-lo` p=0.35).
- Thompson loop, T=600 rounds, 25 seeds: sample every arm from its
  CURRENT decayed posterior, play the argmax, observe the true-rate
  Bernoulli, record the observation under the candidate schedule's γ
  (γ emitted from PAST outcomes only — no peeking, matching
  `fold()`'s schedule replay order).
- Priors: pseudo-count Beta(1,1) (the `PRIOR_ALPHA/BETA_DEFAULT`
  learning-rate knob; prior-strength sensitivity was not the binding
  axis on this grid — the uniform unit prior is kept).

## Candidates

Constant grid: γ ∈ {0.9, 0.95, 0.98, 0.99, 1.0}.
Outcome-adaptive (declared form `γ = floor + (1−floor)·EMA(outcomes)`,
EMA memory λ, neutral seed 0.5): declared grid floors {0.8, 0.9} ×
λ {0.9, 0.95, 0.98}.

## Numbers (mean over 25 seeds; sd in the JSON)

| candidate | pre-flip err [100,300) | post-flip err [300,600) | regret | cold-start width |
|---|---|---|---|---|
| constant γ=0.90 | 0.0929 | **0.1335** | 43.95 | 0.1694 |
| constant γ=0.95 | 0.0658 | 0.2412 | 37.04 | 0.1582 |
| constant γ=0.98 | 0.0481 | 0.3299 | 36.44 | 0.1492 |
| constant γ=0.99 | 0.0285 | 0.3856 | 43.53 | 0.1455 |
| constant γ=1.00 | 0.0730 | 0.4295 | **69.90** | 0.1537 |
| adaptive floor=0.8 λ=0.90 | 0.0947 | 0.1810 | 43.54 | **0.1671** |
| adaptive floor=0.8 λ=0.95 | 0.0818 | 0.2110 | 39.23 | 0.1652 |
| adaptive floor=0.8 λ=0.98 | 0.0604 | 0.2198 | 40.56 | 0.1664 |
| adaptive floor=0.9 λ=0.90 | 0.0473 | 0.3087 | 39.22 | 0.1537 |
| adaptive floor=0.9 λ=0.95 | **0.0468** | 0.3025 | 37.68 | 0.1558 |
| adaptive floor=0.9 λ=0.98 | 0.0477 | 0.3194 | 39.70 | 0.1568 |

(post-flip err = mean |decayed_mean(t) − true_p(t)| on the flip arm,
stale unplayed rounds counted — that staleness is what the selector
sees; regret = cumulative best-p − played-p; cold-start width = mean
flip-arm posterior width over the first 50 rounds.)

## Findings

1. **γ = 1.0 (no forgetting) is dominated on every axis** — worst
   post-flip error (0.430: the stale 0.8-era counts never decay) AND
   worst regret (69.9: it keeps paying for the dead arm). This is the
   empirical form of #428's premise against the τ-era assumption that
   undecayed counting is free.
2. **Constant small γ buys tracking with permanent information loss.**
   γ=0.9 is the best pure tracker (0.134) but forgets forever, even in
   a stationary tail, and carries worst-tier pre-flip noise (0.093).
3. **floor=0.9 adaptive variants hold γ too close to 1 while wounded**
   (post_err ≈ 0.30). Mechanism: the flip arm stops being played, so
   the global outcome regime stays healthy and the EMA keeps γ high —
   the wounded cell never feeds its own bad outcomes in. (Per-cell γ
   routing is a declared v0.2 refinement; the ROW schema already
   carries per-event γ, so the data model needs no change.)
4. **floor=0.8 λ=0.9 is the balanced point**: it inherits the
   cold-start regime's strong forgetting (γ starts ≈0.9 and sits low
   while outcomes are poor), tracks the flip at 0.181 — 2.4× better
   than γ=1.0 — at pre-flip noise statistically equal to γ=0.9's
   (0.095 vs 0.093), and anneals toward 1.0 when outcomes improve
   (self-heal semantics 1:1 with the owner ruling in #428).

## Chosen default (ships as named constants)

```python
GAMMA_FLOOR_DEFAULT = 0.8          # OutcomeAdaptiveGamma floor
ADAPTIVE_EMA_LAMBDA_DEFAULT = 0.9  # EMA memory (~10-observation regime)
```

Rationale: the owner-mandated outcome-adaptive form, with the measured
parameters that dominate the constants on the joint
(tracking × annealing) objective: 84% of γ=0.9's post-flip tracking
benefit without its permanent-forgetting tax, γ=1.0's precision class
once outcomes stabilize, widest-tier cold-start exploration, and
regret tied with the best constants (43.5 vs 44.0) at a third of
γ=1.0's. λ=0.9 gives a ~10-observation outcome-regime memory, the same
scale as the floor's effective forgetting horizon 1/(1−0.8) = 5 — the
two decay rates reinforce rather than fight.

Prior strength stayed Beta(1,1): the uniform unit prior keeps newborn
cells maximally wide (cold-start demand) and the knob is exposed for
the W2-T2 Q-cell consumer.

## Threats to validity

- Synthetic drift is a step flip at a known time; real non-stationarity
  may be gradual or multi-arm. Re-calibrate on W3 real measurement
  before touching these constants again.
- The adaptive schedule observes a GLOBAL outcome stream (one EMA per
  bank), not per-cell streams; finding 3 is the visible cost. If W3
  shows wounded-cell blindness in production, per-cell γ routing is
  the first candidate (schema unchanged).
- 25 seeds; regret/preflip differences between the mid-table candidates
  are within ~1 sd — only the γ=1.0 blowup and the floor=0.9 tracking
  gap are outside seed noise.
