# Design — phase4-voi-priority

## Formula
score(a) = [0.45·L(a) + 0.30·D(a) + 0.25·N(a)] / cost(a)

## Signals (all mechanical, zero LLM)
- L leverage: count OPEN claims depending on a (depends_on reverse edge), normalized by max; terminal fact → 0
- D discriminator: active competitor_group(≥2 OPEN)=1.0 / answers_question=0.5 / else=0.2
- N novelty: 1 − min(1, same-action-category prior terminal facts / 3)
- cost: TIER_COST[action_tier] = {1:1.0, 2:3.0, 3:10.0} (expensive tier penalized in denominator)

## Why non-degenerate
L requires full DAG traversal (exceeds LLM working memory). N requires evidence-region accounting. cost/tier is a registry constant. None duplicate the LLM's semantic judgment (which the old static value tag did).

## Weights
(0.45/0.30/0.25) are starting values; calibration via E4.1 historical replay is deferred (needs ≥3-5 claims with known resolution order).
