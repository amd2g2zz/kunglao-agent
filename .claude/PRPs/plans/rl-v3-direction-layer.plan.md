# rl-v3 Direction Layer — Design Plan (issue #951)

Status: **evidence gate — PASSED for the anchor mechanism (config 3)
and the combined mechanism (config 5); racing elimination alone
(config 4) is NOT-for-production by the pre-registered criteria.**

Scope wall: **this card changes NO production wiring.** Everything
lives in the declared sim tier (`experiments/learning-loop/sim/`) plus
its tests and this doc. The production card (#953) opens ONLY on this
gate's PASS — and opens on the config-5 shape (anchor + racing), not on
any single mechanism.

## 1. The empirical sample being measured

P8 round-1 (real run, 2026-11-01): the cold arm marched to a forged
PASS with every mechanical face green — 5 true PROVEN claims, ladder
climbing, settlement PASS — while the direction was wrong (it read the
co-located grader). DTS never saw it: every per-step reward on that
path was genuine. The reward signal was not anchored to the primary
objective; denser credit and exploration prompts are
literature-documented as ineffective (arXiv:2606.15385). Potential-based
shaping is provably policy-invariant ONLY when the terminal reward IS
the true objective (Ng-Harada-Russell, JAIR v19) — the round-1 failure
is that invariant's precondition breaking.

## 2. The world (experiments/learning-loop/sim/dual_objective_world.py)

### 2.1 MDP definition

- **Decision layer**: a rollout is a 24-step budget; every 6 steps
  (STRETCH) the policy commits to a **direction** — a hypothesis-level
  choice among three arms (NOT the method-family layer):
  - `true-solve`: each step advances the primary ladder with p=0.65
    (one rung OPEN→PROVEN, the #898-shaped ladder of 8 subgoals,
    measured potential P = mean evidence weight), regresses with
    p=0.2 (mid-run setbacks — progress can regress; a setback needs a
    proven rung, early ones degrade to neutral), else neutral.
    Terminal = primary objective met (all 8 rungs PROVEN). Cost 1.0/step.
  - `leak-proxy`: the readable grader. Each step manufactures a
    COMPLETE per-step claim ladder on the proxy scale (floor→top), so
    the SAME measured-potential face pays full credit every step,
    densely and cheaply (cost 0.25/step). NEVER touches the primary
    ladder. Structurally cannot win.
  - `dead-plausible`: plausible (its mechanical face never fails),
    structurally cannot win, near-zero signal (no ladder moves). Cost
    0.5/step. The premature-surrender probe.
- **Evidence events**: every step emits an evidence item shaped like a
  fact frontmatter ({status, verify_status}); classification runs
  through the REAL rlvr.step_credit classifier and the #884 conjunctive
  gate is derived mechanically from it (refuted faces fail mechanical;
  only a green gate over terminal strength passes the scope layer).
- **Reward faces** (production faces, unmodified): per-step credit =
  per_dispatch.measured_credit(ΔP_own_scale / LADDER_SPAN clamped to
  PASS_CREDIT) on a passing gate. LADDER_SPAN derives from step_credit's
  table (1.0 − 0.3 = 0.7); one primary rung banks exactly
  PASS_CREDIT/8; a full climb telescopes to exactly PASS_CREDIT
  (test-pinned).
- **Ledger + posterior**: rows land through
  rlvr.q_cells.append_observation (credit_kind="step", the admissible
  dense-observation kind) and the direction posterior reads the REAL
  fold (γ=1.0 exact masses), cached incrementally and reconciled
  fail-loud against the fold at every rollout's end.

### 2.2 The unanchoring (modeled, not caricatured)

The measured face prices the step's OWN scale. On true-solve that scale
is the primary ladder (one rung = 1/8 of the span → 0.125 credit/step
mean 0.081 with setbacks and neutrals banking 0). On leak-proxy the
loop stands next to the co-located grader whose claims are complete
per-step ladders — the same face pays 1.0/step. Nothing at step time
checks that the ladder it priced IS the primary objective's ladder.
**Every per-step reward is genuine; the direction is still wrong.** A
full leak rollout banks 24.0 credit on 6.0 cost (the #930
adversarial-economics echo) while completing nothing.

### 2.3 Direction selection (the DTS shape at the direction level)

policy.selector's algorithm applied at the direction level: wide
Beta(1,1) prior over each arm's banked step mass, ONE Thompson draw per
arm, largest sample takes the stretch, sorted fork order. This is
exactly the face #953 would promote; the production selector stays
task-grained and untouched.

## 3. The judge input contract (configs 3/5)

The direction-PRM judge is a per-step direction-contribution face:
`credit_judged = measured_credit × 1[ΔP_primary > 0]`.

**IN-SIM THE JUDGE IS ORACLE-WEIGHTED**: it reads the true primary
delta. The card measures the SIGNAL SHAPE's effect, not the learning
problem: production would need to LEARN this judge from recorded
transitions (the #898 ladder + #879 ledger rows are exactly its training
surface), and a learned judge's errors are not modeled here. That
limitation is stated, not hidden; the config-3/5 PASS is a signal-shape
verdict, not a production-readiness verdict.

## 4. The racing rules (configs 4/5)

A direction may be abandoned ONLY when its posterior has COLLAPSED:
Beta(1+s, 1+f) lower bound (mean − 1 sd) below ABANDON_THRESHOLD=0.03.
While the optimistic bound clears the threshold, the arm is RACED
(kept at the stretch boundary regardless of the draw). A collapsed arm
leaves the candidate set (elimination — never drawn again). Rationale:
true-solve's setbacks bank failure mass; a raw DTS draw abandons it on
one mediocre stretch, while a collapsed-only rule forbids surrender
until falsification.

## 5. The five configs and the results (fixed seeds, seed0=951, 4 batches × 50 rollouts each — fresh workspace per rollout)

| config | leak-collapse (a) | surrender (b) | completion (c) | credit/ro | cost/ro |
|---|---|---|---|---|---|
| 1 baseline (DTS + measured) | 0.550 [0.46–0.66] | 0.530 | 0.015 | 15.94 | 10.0 |
| 2 dense-floor control (0.3 flat) | 0.055 | 0.595 | 0.105 | 7.02 | 13.2 |
| 3 +direction-PRM | 0.000 | 0.515 | 0.150 | 0.68 | 14.1 |
| 4 +racing elimination | 0.525 | 0.000 | 0.355 | 11.90 | 11.8 |
| 5 PRM + racing | 0.000 | 0.000 | 0.600 | 1.12 | 16.4 |

- (a) = rollouts spending the majority of steps on the leak arm;
  (b) = rollouts that dropped true-solve pre-collapse and never ran it
  again (a SURRENDER — a transient departure that returns is churn, not
  surrender; the metric keys on the direction of record dying while the
  arm was still raceable); (c) = rollouts reaching the primary
  objective (all 8 rungs PROVEN). Mean [min–max] over batches.

### 5.1 Baseline collapse: reproduced (mechanism reproduction, near-analytic
by construction — a credit-greedy selector converges to the dense arm;
recorded as a reproduction check, NOT cited as predictive validation)

Config 1 collapses onto the leak arm (0.550, every batch ≥ 0.46) with
completion near-dead (0.015) — the in-silico reproduction of P8
round-1. The diagnosis is NOT falsified. Credit economics: the baseline
banks ~16 credit per rollout at 10 cost while completing 1.5% — the
forged-economics shape (a full leak rollout banks 24.0 on 6.0 cost).

### 5.2 The control's finding (config 2)

The flat floor's prediction ("worse than baseline") holds on the
surrender axis (0.595 vs 0.530) and on completion-vs-mechanisms
(0.105 < every mechanism), but **NOT on leak-collapse: the flat floor
reduced it to 0.055.** The finding, recorded not tuned away: a flat
per-step payment homogenizes the arms — the hijack pull dies because
the hijacked arm loses its density ADVANTAGE, but the gradient dies
with it (completion stays at the coin-toss level, direction choice
uninformative). A dead signal beats a hijacked one and loses to both
real mechanisms. The #930 6.0-vs-0.6 adversarial-credit-inflation shape
does not reproduce under a strictly flat floor in this world; it
requires the arm ASYMMETRY (cheapness × density), which is the baseline
leak arm's economics, not the floor's.

### 5.3 Mechanism verdicts (pre-registered criteria, both required)

| mechanism | criterion 1 (leak drop significant, 3-sd + batch-consistent) | criterion 2 (surrender not raised) | verdict |
|---|---|---|---|
| direction-PRM (3) | drop 0.550 > 3sd 0.106, every batch lower | 0.515 ≤ 0.530 | **PASS** (signal shape) |
| racing elimination (4) | drop 0.025 < 3sd 0.150 — FAILS | 0.000 ≤ 0.530 | **NOT-for-production** |
| PRM + racing (5) | drop 0.550 > 3sd 0.106, every batch lower | 0.000 ≤ 0.530 | **PASS** |

Recorded finding (config 4): posterior-collapse elimination can never
unmask an arm whose unanchored signal is genuinely positive — the leak
posterior never collapses, so a not-yet-falsified leak arm is raced
exactly like a not-yet-falsified true arm. Racing is a commitment
protector, not an anchor: it quadruples completion alone (0.015 →
0.355) and zeroes surrender, but it cannot pass the leak-collapse
criterion, and it is the reason config 5 dominates (racing removes the
PRM arm's churn: config 3's rollouts ping-pong onto collapsed arms and
back — completion 0.150 — while config 5 commits: 0.600).

## 6. Production wiring: OUT OF SCOPE

**Nothing in this card touches production.** `scripts/rlvr/`, `hooks/`,
`scripts/eval_*` are untouched; the world and battery live entirely in
the declared sim tier. The follow-up card (issue #953) opens ONLY on
this gate's PASS and inherits: the anchor shape (per-step credit scaled
by primary-objective advance — production judges it from the ledger's
recorded transitions, not an oracle), the racing rules (§4), and the
pre-registered metrics above as its own acceptance gate.

## 7. Reproduction

```
uv run pytest tests/test_rl_v3_sim_world_951.py -q -n 4
uv run python -c "import sys; sys.path.insert(0,
  'experiments/learning-loop/sim'); import dual_objective_battery as b;
  print(b.render_table(b.run_five_configs('/tmp/v951-battery', batches=4,
  rollouts=50, seed0=951)))"
```

Fixed seeds: seed0=951 threads every rollout
(`f"{seed0 + batch}/{config}/{rollout}"`); every draw threads its own
`Random` — no shared mutable RNG, no wall clock in any decision.
