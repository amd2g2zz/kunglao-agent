Design (pre-registered BEFORE any run — owner honesty rules):

## World model
S=6 signature classes × F=8 families (#432 vocabulary sample). True success p(s,f) drawn per WORLD SEED from a sparse mixture: exactly 2 strong arms per class (Beta(9,2)-ish, mean ~0.8), the rest weak (mean ~0.15). Regimes: (R1) sparse-strong as above; (R2) control degenerate-uniform (all ~0.5 — no signal; both policies must tie, a sanity discriminator); (R3) one-dominant (single 0.9 arm, rest 0.1). P_LLM prior: weak informative — uniform 1/F + 0.1 tilt toward a RANDOM per-class arm (NOT the true strong arm — the kernel must earn discovery).

## Policies (paired seeds per cell)
- kernel: receipt = sample_method_family(sig, prior, store, rng); outcome ~ Bernoulli(p(s, chosen)); append InMemoryStore row {credit: 1.0 on success, 0.0 on failure}; next sample. (The fold runs inside the sampler per its contract.)
- uniform: rng.choice(families) — same outcome stream construction.
- eps-greedy (ε=0.1): empirical-mean arm with prob 0.9 else uniform.

## Metrics (per class, per n∈{5,10,25,50,100} cumulative outcomes)
cumulative regret vs oracle (p*−p_chosen summed); waste-acts = failures before first success; first-success act index. Aggregates: mean per class, sign-test across 200 paired seeds per cell.

## PRE-REGISTERED discriminators (written before running)
1. kernel ≈ uniform at n=100 in R1 → implementation defect → unit-level trace audit of fold/observe path.
2. separation only at n≥50 → vocabulary/reward sparsity (families too coarse to discriminate early).
3. sign flips across classes → state-key problem (signature hash buckets vs feature pools) → re-run with KUNGLAO_PREDICT_BEFORE_TRY-style pools.
4. kernel loses to eps-greedy but beats uniform → sampling noise too high; tune nothing, report.

## Real-data floor
Replay both policies on the committed feature-table/1 fixture (2 usable runs) — expected: no separation (underpowered calibration; the honest floor).

## Honesty rules
One pass, no world tuning until the kernel wins. Losses published as loudly as wins.
