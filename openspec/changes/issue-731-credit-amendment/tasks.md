# tasks — issue-731-credit-amendment

## 1. The RED contract

- [ ] `tests/test_credit_amendment_731.py`: the pins —
      amendment rows fold verbatim (signed Δsuccess/Δfailure, no band,
      no tiebreak, no γ-EMA feeding, admitted to the posterior);
      `amend_settlement` moves banked mass to the target exactly once
      and re-runs no-op; the honest gaps (no banked row → nothing;
      already-current → nothing); the pending-row fallback (pruned
      dispatch row still amends via the banked row's identity); the
      settle pass reconciles a corrected ledger to the bank and
      repairs a missed bank; replays without corrections stay
      byte-identical no-ops; solve/step/step_calibration rows are
      unchanged
- [ ] confirmed RED before implementing

## 2. The one signed-kind tuple

- [ ] `scripts/rlvr/q_cells.py`: `CREDIT_KIND_CREDIT_AMENDMENT` +
      `SIGNED_CREDIT_KINDS`; the fold's EMA-exclusion and verbatim-mass
      checks read the tuple; `_coerce_credit` takes both kinds signed
      with `failure_delta` legal on both
- [ ] `append_observation(..., reason=None)` — optional column,
      emitted only when set

## 3. The amendment face

- [ ] `q_cells.banked_mass(ws, dispatch_id)` — effective `(s, f,
      n_rows)` from the observation log (settlement + amendment
      sources), mirroring the fold's admission
- [ ] `q_cells.amend_settlement(ws, dispatch_id, target_credit, *,
      reason)` — Δ to target, idempotent, identity fallback through
      the latest banked row; rows carry `source: "credit-amendment"`

## 4. The pass face

- [ ] `scripts/rlvr/scalar.py`: `_reconcile_q_cell_bank` (missed-bank
      repair via the q-cell faces directly — no strategy-store/L1
      re-fire — + amend-to-ledger); the settle loop reconciles every
      already-settled row; the result dict reports `amended`

## 4b. Defensive reader fixes (audit findings)

- [ ] `scripts/rlvr/meta_arms.py` `mc_propensity`: Beta parameters
      floored at the +1.0 prior (`max(s,0)+1, max(t-s,0)+1`) — a
      negative-correction stream can no longer crash `betavariate`
- [ ] `scripts/rlvr/strategy_store.py` `cell_count`: excludes
      `credit_amendment` rows (a correction is not a new observation)

## 5. Gates

- [ ] GitNexus impact recorded for every edited symbol (fold,
      _coerce_credit, append_observation, settle_round_credit — all
      LOW, pre-verified)
- [ ] targeted suites green: test_credit_amendment_731 +
      test_credit_settle_634 + test_step_level_credit_712 +
      test_q_cells_429 + test_l1_planner_718 + test_arming_shape_733 +
      test_late_arm_oracle_730
- [ ] `openspec validate issue-731-credit-amendment --strict` passes
- [ ] review-gate mint (1 whitelisted reviewer, diff_sha256 pinned)
- [ ] CI green before merge (dev branch protection)
