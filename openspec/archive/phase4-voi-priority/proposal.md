# phase4-voi-priority

## What
Rewrite priority_ratio scoring from additive static-value-tag (0.35·Δdisc + 0.35·E_unlock + 0.10·unc)/NEXT_TIER_CHEAP to VoI proxy: score = [0.45·L + 0.30·D + 0.25·N] / TIER_COST.

## Why
The old "value" dimension was a static semantic tag (PRIMARY=1.0/competitor=0.6/else=0.2) that duplicated the LLM's own in-context judgment — degenerate under full-state. Empirical proof: C-401 and C-402 tied at 0.696 under the old scorer (it cannot distinguish a low-VoI re-verification from a high-leverage process-trust claim). The new L/D/N are mechanical signals the LLM cannot reliably compute in-context (graph traversal, coverage entropy, tier cost) — non-degenerate.

## Scope
- scripts/priority_ratio.py: Action fields delta_disc/expected_unlock/unc → leverage/discriminator/novelty; EvidenceView +fact_count_by_category; new action_cost/cheapness/_reverse_deps/_active_competitor_groups/_discriminator/_novelty
- scripts/kunglao-decide.py: _cheapness_order updated for new Action schema
- tests/test_priority_ratio.py: 10 new tests (formula/leverage/discriminator/novelty/cost/determinism/C-401≠C-402 regression)
- LLM never enters the score (pure function, deterministic)

## Acceptance
- test_priority_ratio.py 10/10 green
- full suite green
- C-401 ≠ C-402 when leverage differs (regression test)
