# issue-712-step-level-credit — dense reward at step boundaries

## Why

Ladder credit (`scalar.round_credit`) settles only at claim-terminal: a
10-step rollout produced exactly ONE learning signal, the step-level Φ
increment was degenerate (S9: 83/85 = 0), and during a multi-hour claim
neither the Q-cell Beta nor the sampling distribution moved — the exact
residue #690 fixed for the LEDGER (steps, transitions, barriers) but not
for the REWARD. Turn-level dense credit is the researched fix (TIPS
2603.22293, TRACE 2607.13988; AgentPRM process rewards): score each
step's own evidence at the step boundary, then reconcile at the end.

## What Changes

1. **`step_credit = f(evidence_quality, verification_status)`**
   (`scripts/rlvr/step_credit.py`) — over the facts the step itself
   touched (mtime window `(last settled step, this settle]`, claim
   scoped): cross-validated (terminal status × green verifier gate) =
   1.0, unverified (or no evidence) = 0.3 provisional, refuted (REFUTED
   status or red gate) = 0.0, each weighted by the ICD-203 Admiralty
   source-reliability letter when provenance carries one.
2. **SubagentStop banks immediately** (`step_grain.settle_step` →
   `q_cells.observe_step_credit`) — one `credit_kind: "step"` row per
   step into the cell the claim's pending dispatch opened: the Beta
   moves at every admitted step boundary (band-valued information
   options stay massless, per the #678 fold rule), before
   claim-terminal (a 10-step rollout = 10 observations AND 10
   transitions).
3. **Claim-terminal calibration** (`scalar._bank_q_cell_credit`) —
   when step credit already banked (`q_cells.step_credit_totals`,
   n > 0) the terminal bank is the residual
   `ladder_credit − Σ(step_credit)` as ONE signed
   `credit_kind: "step_calibration"` row (plus the matching Δfailure
   mass): over-credit is clawed back, under-credit topped up, and the
   folded endpoint equals the step-less legacy endpoint — dense credit
   changes the PATH, not the DESTINATION.
4. **Backward compatible by branch** — a dispatch with n = 0 step rows
   takes the unchanged `observe_settlement` face: byte-identical legacy
   rows, identical fold arithmetic (the acceptance: claims that settle
   before this change work unchanged).

## Non-goals

- Register-backed certification (#651) as the step-time quality signal —
  it by construction only exists at claim-terminal; the two-channel
  step-time view (claim strength × verifier gate) plus the calibration
  reconcile is this card's scope.
- Learned source reliability (#705 lineage) — the Admiralty letter
  weight is a declared policy map; swapping in a learned reliability
  keeps the `reliability_weight` seam.
- Changing Φ, the round-credit ladder itself, or the #705
  solve/verification admission rule (step credit rides the same
  admission: admissible, solve-like).
