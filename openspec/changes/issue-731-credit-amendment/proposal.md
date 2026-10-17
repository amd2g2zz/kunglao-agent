# issue-731-credit-amendment — the learning signal tracks the ledger

## Why

`scalar.settle_round_credit` banks a dispatch's ladder credit into the
Q-cell store ONCE — at the first settlement (the settlement-presence
guard). Every later correction of the ledger value (the #433 late-cite
amendment, evidence repair that shifts `r`) refines the LEDGER only:
the observation log is append-only, re-banking would double-count, so
the guard refuses. Net effect: **the posterior carries the old wrong
credit forever** — the learning signal has no amendment path, and a
wrong first write poisons every downstream decision that reads the
cell.

The same pass also leaves a second hole: when the ledger settled but
the Q-cell bank itself failed (the bank is fail-open telemetry), the
guard never retries — the dispatch is permanently bank-less.

## What Changes

1. **ONE new signed credit kind** — `credit_kind: "credit_amendment"`
   rides the #712 `step_calibration` semantics verbatim: signed Δsuccess
   (row `credit`) + Δfailure (row `failure_delta`), applied outside the
   band and the tiebreak, excluded from the γ EMA, admitted to the
   posterior. A module-level `SIGNED_CREDIT_KINDS` tuple names the two
   kinds once; the fold, the EMA-exclusion check, `_coerce_credit` and
   the mass read all share it.
2. **A distinct row source** — amendment rows carry
   `source: "credit-amendment"`, NOT `"settlement"`: every ad-hoc
   reader that keys on the settlement source (the e2e repeat-failure
   feed, the proposal/level priors, warm pools) stays blind to
   corrections by construction, and only the fold's signed branch (and
   the two named reader fixes below) consumes them.
3. **The bank reads its own effective mass** —
   `q_cells.banked_mass(ws, dispatch_id)` returns `(success, failure,
   n_rows)` summed from the SAME append-only log the fold consumes
   (settlement + amendment rows; solve rows band-skipped and
   tiebroken exactly as the fold does; signed rows verbatim).
4. **`q_cells.amend_settlement(ws, dispatch_id, target_credit, *,
   reason)`** — computes Δ = band-aware target − (banked mass + step
   mass) and appends ONE amendment row. Idempotent by construction:
   already-current → no row. The matched cell identity prefers the
   pending dispatch row; when none exists it falls back to the identity
   carried by the latest banked settlement row (prune-safe, strictly
   stronger than the #712 face). No banked row at all → the honest gap,
   nothing written.
5. **The settle pass reconciles** — every already-settled dispatch
   (replays, late-cites, duplicates) runs
   `scalar._reconcile_q_cell_bank`: bank-less → full first bank via the
   q-cell faces DIRECTLY (never `_bank_q_cell_credit` — the strategy
   store and L1 return must not double-write); banked →
   `amend_settlement` toward the ledger's current value. The pass
   result names the reconciled dispatches under `amended`.
6. **The `reason` rides the row** — `append_observation` grows one
   optional `reason` column (emitted only when set; every other caller
   byte-identical).
7. **Two defensive reader fixes** (harness-audit findings, both live on
   dev): `meta_arms.mc_propensity` floors the Beta parameters at the
   +1.0 prior (accumulated negative credits could drive
   `betavariate` ≤ 0 and silently drop OPE propensity rows); and
   `strategy_store.cell_count` excludes `credit_amendment` rows
   (a correction is not a new observation — the n_min evidence gate
   must not count it).

## Out of scope (v1, named — audit-driven)

- **Case-posterior pair freeze** (harness audit): `record_case_settlements`
  observes the (case, claim) pair ONCE — a PROVEN→REFUTED flip can
  never re-observe, and `priority_ratio` Thompson-prices dispatchable
  claims from exactly these posteriors. Same staleness family,
  different mechanism (signed counter-observation keyed by the pair) →
  its own card, not silent scope creep here.
- `strategy_store` value rows and the #718 L1 rollout return also
  consume the settled `r` and stay first-write (each needs its own
  delta semantics; the reconcile never re-fires their writers).
- The γ-attenuation question (an amendment lands at weight 1.0, the
  mass it corrects was banked at γ^k) is inherited from #712's raw-sum
  posture, not newly introduced here.
- The episode-tier leg heals missed-first tiers but freezes corrected
  values (engine-dependent, rare) — named, untouched.
- The persisted rank payload (`rank_face`) is stale-by-design with
  explicit stale/age flags and heals at rank cadence.
