# EX-6 — option-death trap replay A/B (issue 461 Phase 2)

Reproduce: `uv run --project . python experiments/ex6_option_death.py`
(raw numbers: `experiments/ex6-results.json`, same commit; deterministic
— byte-identical across reruns, pinned in
`tests/test_ex6_option_death_461.py`).

**DECLARED SYNTHETIC** — the environment is EX-4's five-step trap
truth table (frida-detected → unidbg-env-error → static-tool-limit →
encrypted-layer → breakthrough-at-decryptor) replayed through the REAL
faces (`obstacles.record` with probe artifacts, q-cell dispatch +
settlement rows, `q_cells.sample_method_family`, the termination
verdicts) on persistent per-arm workspaces. Nothing here is campaign
data.

## Protocol

Three arms over one persistent workspace each (registry + q-cell log
persist across the 40 episodes per arm — that persistence IS the
learning), 8 acts per episode budget, paired seeds per (episode, act)
shared across arms:

| arm | label | sampler | failure recording |
|-----|-------|---------|-------------------|
| A | decay-only | no death kwarg (current kernel) | settlement credit 0 |
| B | attribution+termination | termination verdicts threaded (dead → ARM_FLOOR) | + obstacle rows (the Phase-1 protocol) |
| C | cause-free control | termination consulted | NO obstacle rows |

Non-real faces (declared): uniform P_LLM over the five registered
families (production hosts measure the proposal channel; pinning the
prior makes arm deltas attribute to termination), deterministic truth
table (no Bernoulli draws).

Disclosed asymmetry: arm B's obstacle recording advances ob= at every
failure, fragmenting its q-cell failure evidence across signatures
(the family anchor is SHRINK_CAPped at 8) — B's ordinary DTS demotion
is WEAKER than A's for the same failure count. B's advantage comes
from the termination floor (fires at 2 attributed same-cause
failures), measured on a slightly weakened baseline: conservative.

## Results (ex6-results.json, this commit)

| metric | A decay-only | B attribution+termination | C cause-free |
|--------|-------------|---------------------------|--------------|
| breakthrough rate | 0.950 | **1.000** | 0.950 |
| mean acts to breakthrough | 2.579 | **1.475** | 2.579 |
| mean wasted acts (dead families) | 1.900 | **0.475** | 1.900 |
| dead families at end | none | all four trap families | none |

Reading:

- **B terminates exactly the four trap families** (the (kind, family)
  cells cross 0.75 under repeated ATTRIBUTED failures) and reallocates
  the sampling mass to the breakthrough family — 100% breakthrough,
  wasted acts cut 4× (1.90 → 0.475).
- **crypto-core-identification stays alive in every arm** — it never
  records an obstacle row, so no death evidence exists for it; it is
  the beneficiary of termination, never its target.
- **C is byte-identical to A** — the cause-free control: consulting
  termination over a workspace whose failures were never attributed
  changes nothing (the zero-registry rule threads no kwarg at all).
  Cause-free failures never terminate; they need attribution first.
  This is the owner's core ruling demonstrated end-to-end.
- The learning is visible within arm B: the dead cells cross during
  the early episodes (episode 1 is draw-identical to A by the paired
  design; divergence starts at the first floored act) and every later
  episode starts with the four families already floored.

## What this licenses

The issue's MC replay A/B acceptance: attribution-in-state + learned
termination beats decay-only on the trap trajectory, cause-free never
terminates, no rule or gate anywhere in the loop — the entire
actuation is a floored sampling weight (ARM_FLOOR 0.1, revivable).
