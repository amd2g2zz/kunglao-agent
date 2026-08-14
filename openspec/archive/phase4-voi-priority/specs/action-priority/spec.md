# Spec Delta — phase4-voi-priority

## ADDED Requirements

### Requirement: Action priority scoring

The orchestrator ranks dispatchable actions by a mechanical Value-of-Information proxy divided by tier cost. The score is a pure function of (claims, claim_deps, evidence) with zero LLM calls; the LLM only writes claims (seed) and facts (result), never the ranking.

**Changed from**: additive static-value-tag `(0.35·Δdisc + 0.35·E_unlock + 0.10·unc) / NEXT_TIER_CHEAP`, where the "value" dimension was a frozen semantic tag that duplicated LLM judgment and caused C-401 = C-402 = 0.696 (degenerate tie).

**Changed to**: `[0.45·L + 0.30·D + 0.25·N] / TIER_COST`.

#### Scenario: high-leverage claim ranks above low-leverage
- WHEN claim A unblocks 3 OPEN downstream claims and claim B unblocks 0
- THEN A.leverage > B.leverage AND A.score > B.score

#### Scenario: terminal claim has zero leverage
- WHEN claim A already has a terminal fact
- THEN A.leverage == 0.0

#### Scenario: active competitor group tops discriminator
- WHEN claim A is in a competitor_group with ≥2 OPEN members
- THEN A.discriminator == 1.0

#### Scenario: expensive tier penalized
- WHEN two claims differ only in evidence_tier_attempted (0 vs 2)
- THEN the cheaper-tier claim has lower cost and higher-or-equal score

#### Scenario: C-401 vs C-402 no longer tied
- WHEN C-402 unblocks downstream claims and C-401 does not
- THEN C-402.score > C-401.score (breaks the historical 0.696 tie)

#### Scenario: scoring is deterministic (zero LLM)
- WHEN priority_ratio is called twice with identical inputs
- THEN the outputs are identical (pure function, no hidden state or LLM)
