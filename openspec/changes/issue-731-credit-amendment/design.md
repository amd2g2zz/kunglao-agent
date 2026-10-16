# design — issue-731-credit-amendment

## The semantics choice

A ledger correction is a SIGNED DELTA against banked mass — exactly the
shape #712 built for the step residual (`step_calibration`). Inventing
a second mechanism (a retraction face, a rewrite pass) would fork the
fold's semantics; reusing the signed-delta branch needs only a second
kind name:

```python
CREDIT_KIND_CREDIT_AMENDMENT = "credit_amendment"
SIGNED_CREDIT_KINDS = (CREDIT_KIND_STEP_CALIBRATION,
                       CREDIT_KIND_CREDIT_AMENDMENT)
```

The fold's two kind checks (EMA exclusion, verbatim mass), the append
boundary's signed validation (`_coerce_credit`) and the mass read all
switch to the tuple — one definition, four consumers, no drift.

## The source boundary (harness-audit driven)

The q-cell log has ad-hoc readers besides the fold. On dev tip,
`e2e/checkpoints.py`'s repeat-failure face keys on
`source == "settlement" and credit < 0.5`; the proposal/level priors
count dispatch rows only. Amendment rows therefore carry
`source: "credit-amendment"` — **every settlement-keyed reader stays
blind by construction**, and the fold's signed branch plus
`banked_mass` accept both sources by kind.

Two readers survive the boundary and get one-line defensive fixes:

| reader | exposure | fix |
|---|---|---|
| `meta_arms.mc_propensity` | sums raw credit over ALL rows (no filter); negative rows can drive `Beta(s+1, t−s+1)` parameters ≤ 0 → `betavariate` raises → the fail-open caller silently drops the OPE propensity | floor both parameters at the +1.0 prior: `max(s, 0) + 1.0` / `max(t − s, 0) + 1.0` |
| `strategy_store.cell_count` | counts rows by signature_hash with no kind filter → a correction inflates the n_min evidence gate | skip `credit_amendment` rows |

Everything else in the reader family heals (recomputes from the log per
call) or is filtered — verified by the 2026-10-16 three-agent harness
audit (Q-cell readers, store/MARL/L1, pass legs + ledger readers).

## The reconciliation arithmetic

```
target   = mass_targets(row.r)                 # clamp01 + band → (s, f)
effective = banked_mass(did) + step_credit_totals(did)
Δ        = (target.s − effective.s, target.f − effective.f)
```

`banked_mass` mirrors the fold EXACTLY (the #712 lesson: the operand is
"what actually banked", read from the same log — never a parallel
tally): solve rows contribute `(tiebroken_credit(c, φ), 1 −
tiebroken_credit(c, φ))` unless band-valued (zero mass, existence
only); calibration/amendment rows contribute `(c, failure_delta)`
verbatim; verification rows are skipped (inadmissible to the
posterior — the fold never banks them, so the read never counts
them); step rows are excluded (step_credit_totals owns that leg). An
UNREADABLE log reads as `None` — distinct from empty — so the
reconcile skips the pass instead of amending against a fabricated
(0, 0). Step rows are already mass-true (`step_credit_totals`).

Target and operand live on the SAME 6-dp grid: `_mass_targets` rounds
both halves to 6 dp before the delta. On an unrounded target a
half-grid point (the ms-precision wall-overrun reward shape lands
exactly there) made the ±1e-6 rounding noise round outward on both
sides — the delta re-fired EVERY pass (the review's non-idempotence
finding, 8/8 passes reproduced). Rounding the target closes it: a
converged pass computes exactly 0.0.

Δ is rounded to 6 dp; **zero-rounded Δ appends nothing** — the
idempotence face (a re-run converges: the amendment row itself enters
the next read's effective mass).

## Identity under correction

The amendment must land in the cell the ORIGINAL bank opened. Match
face, strongest-first:

1. `_match_pending_dispatch` — the dispatch-time row (signature,
   arm_key, recipe triple) — the #712 face;
2. **fallback**: the latest banked settlement row matching the
   dispatch identity — its own signature/method_family/arm_key are the
   cell address, so a pruned dispatch row can never orphan a
   correction (strictly stronger than #712; prune is the named v1
   limitation there);
3. neither → the honest gap, no row.

## The pass face

`_reconcile_q_cell_bank(ws, row)` runs on every already-settled row
(ledger `settlement` present), covering three faces with one guard:

| face | detection | action |
|---|---|---|
| ledger corrected | banked mass ≠ target | `amend_settlement` |
| bank never landed | `n_rows == 0` | first bank via the q-cell faces DIRECTLY (`observe_settlement` / `observe_step_calibration` + the `_calibration_delta` residual) — **never `_bank_q_cell_credit`**, whose strategy-store and L1 legs must not double-write |
| already current | Δ ≡ 0 | no-op (cheap: one log scan) |

Trigger placement: outside `res.get("appended")` — pure replays
(duplicate settlements) reconcile too, so a bank that failed on the
first pass is repaired on the next one whatever the ledger says. The
repair never reports into `banked` (the case-posterior leg keys on
exactly that set — a repaired bank must not re-fire a Bernoulli
observation).

## Byte-identity walls

- `append_observation` rows WITHOUT `reason` are key-for-key identical
  to today's (the column is emitted only when set — the #705/#695
  emission discipline).
- `_coerce_credit` behavior for solve/verification/step/step_calibration
  is untouched (the tuple contains them unchanged; amendment only adds
  a member).
- The fold's solve path (band-skip, tiebreak, EMA, n_pending) is
  untouched — only the kind-tuple checks widen.
- The settle result dict GROWS `amended` (additive; no exact-key pins
  exist in the suite — verified across all 11 consumer test files).
