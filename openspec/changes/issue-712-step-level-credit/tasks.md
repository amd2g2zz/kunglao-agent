# tasks — issue-712-step-level-credit

## 1. The step score (pure face)

- [x] `scripts/rlvr/step_credit.py`: `classify_verification` (green gate ×
  terminal strength / refuted-first), `reliability_weight` +
  `_provenance_weight` (worst Admiralty letter, declared A–F map),
  `item_credit`, `step_credit` (mean; empty → 0.3 provisional floor),
  `evidence_in_window` (mtime window `(since, until]` × exact claim
  channels, fail-open to `[]`)

## 2. The step-boundary bank (SubagentStop)

- [x] `scripts/rlvr/q_cells.py`: `CREDIT_KIND_STEP` /
  `CREDIT_KIND_STEP_CALIBRATION`, `_match_pending_dispatch` (extracted
  from the #462 W5 match), `observe_step_credit`, `_bank_matched`
  (shared result shape), `step_credit_totals`
- [x] `scripts/rlvr/step_grain.py`: `settle_step` scores the step's
  evidence window since the last settled step (first step: the launch
  stash ts) and banks the credit inside its own fail-open cage; the
  returned receipt carries `step_credit` / `credit_banked` (ledger row
  whitelist untouched)

## 3. The claim-terminal calibration

- [x] `scripts/rlvr/scalar.py`: `_calibration_delta` (pure — legacy rail
  clamp + D-678.4a band-aware endpoint → signed Δsuccess/Δfailure) and
  the `_bank_q_cell_credit` branch: n = 0 legacy face byte-identical,
  n > 0 → `observe_step_calibration`
- [x] `scripts/rlvr/q_cells.py`: `observe_step_calibration`;
  `append_observation` takes signed finite calibration credit +
  `failure_delta` (refused anywhere else, ONE warn)
- [x] `scripts/rlvr/q_cells.py` fold: calibration rows applied verbatim
  after the γ weight (no clamp/band/tiebreak), excluded from the γ EMA;
  docstrings updated (`fold`, `append_observation`)

## 4. RED tests

- [x] `tests/test_step_level_credit_712.py`:
  `test_step_credit_banked_at_subagent_stop` (banked at the stop, before
  claim-terminal), `test_ten_step_rollout_produces_ten_signals`
  (10 rows + 10 transitions + per-step mass accrual),
  `test_claim_terminal_calibration_corrects_cumulative_beta` (clawback /
  top-up / refuted-terminal endpoints),
  `test_step_credit_weighted_by_evidence_quality` (three anchors,
  provisional floor, reliability letter, window × claim scoping) + the
  compat pins: `test_backward_compatible_settlement_without_step_credit`
  (legacy row shape) and `test_terminal_endpoint_is_independent_of_step_count`
  (path ≠ destination)

## 5. Review hardening (independent review round 1)

- [x] HIGH — band-interaction operand: `step_credit_totals` counts the
  fold's MASS view only (D-678.4a band-valued information-option rows
  are excluded from both Σ and n — clawing them back would subtract
  mass that was never banked); RED pin
  `test_calibration_never_claws_back_band_valued_steps`
- [x] MEDIUM — spec Req 2 overclaim: strict monotone mass narrowed to
  cross-validated steps (refuted steps move failure mass; band options
  move nothing); proposal/design reworded to the admitted-boundary
  claim

## 6. Verification

- [x] target suite green (`pytest tests/test_step_level_credit_712.py -q -n 2`)
- [x] touched-surface regression green (step_grain / q_cells /
  credit_settle / marl / scalar settlement / round-credit / reward-source
  / blind-settlement / step-ledger / incremental-reward / worker-budget /
  ws2-warm-start / termination / compose family — 662 passed)
- [x] `openspec validate issue-712-step-level-credit` exit 0
- [x] comment-hygiene / formal-code lint baselines re-emitted
- [x] deploy manifest re-emitted (import closure picks up step_credit)
