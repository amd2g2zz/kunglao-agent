# issue-742-case-posterior-amendment — the case posterior tracks the register

## Why

The case-posterior observation pair (case_id, claim_id) is observed
ONCE: the case-observation ledger row is the dedup record (#730) and
`CasePosterior.update` is a pure +1 conjugate. When a claim's settled
outcome is later CORRECTED (evidence flips PROVEN→REFUTED), the ledger
serves the corrected value to nothing — the belief keeps the first
outcome forever. Decision-bearing: `priority_ratio` Thompson-prices
dispatchable claims from exactly these posteriors.

## What Changes

1. **`case-amendment/1`** — a new append-only stamp in the experience
   family recording the pair flip {from_passed, to_passed, d_alpha,
   d_beta, source: "reconcile"}; the original case-observation/1 row
   stays byte-untouched as history. Registered in NATIVE_SCHEMAS.
2. **The pair fold** — `_effective_pair_outcomes` folds both stamps
   (last-amendment-wins) into per-pair (original, effective).
3. **`reconcile_case_settlements`** — compares each observed pair's
   effective outcome with the claim's CURRENT decisive register status;
   a flip applies the ±1 delta to the belief (floored at the Beta(1,1)
   support) belief-first and appends the audit row. Idempotent in the
   fold; honest gaps write nothing.
4. **The pass wires the leg** after fresh+late; the result reports
   `case_amendments`; refusal surfaces in the error join.

## Out of scope (named)

- The runner-path observations (oracle_runner, no ledger rows) are
  outside reconcile scope — the ±1 delta composes with their mass but
  they carry no row-level record to reconcile against.
- The eight-site documented-tolerant OSError gap (#430 follow-up).
