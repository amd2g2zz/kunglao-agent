# design — issue-712-step-level-credit

## 1. The step's evidence (window + claim scope)

`step_credit.evidence_in_window(ws, claim, since_ts, until)` reads
`facts/F*.md` frontmatter for facts with mtime in the HALF-OPEN window
`(since_ts, until]` that name the claim through an exact claim channel
(`claim_id` / `claim_ids` / `claims` / `creator` — never a substring).

- `since_ts` = the previous settled step-record/2 row's ts for the
  session; the first step opens at the dispatch-launch stash ts. Without
  per-step windows every step would re-score the claim's cumulative
  evidence and bank the same credit again.
- Window undecidable (empty/unparseable `since_ts`, non-datetime
  `until`) → `[]` → the provisional floor — fail-open, never a raise
  into the SubagentStop cage.
- Re-touching a fact inside a later window rescores it (verification IS
  step work). The farming shape — poke a proven fact every step —
  inflates Σ(step_credit) and is removed dollar-for-dollar by the
  claim-terminal residual: farming nets zero by construction.

## 2. The verification classes (step-time signals only)

```
vs == "fails" or status == REFUTED            -> refuted      0.0
vs == "passes" and status in {PROVEN,
               VERIFIED, NEGATIVE}            -> cross_validated 1.0
everything else (OPEN/INFERRED/DEFERRED,
pending/partial/stale/absent gate, no facts)  -> unverified   0.3
```

- **Cross-validation at step time** = worker claim strength × verifier
  gate (the two channels that exist mid-flight). The #651 certification
  (register-backed terminals) cannot fire before promotion, so it is
  explicitly NOT the step-time signal; the terminal residual is the
  reconciliation for a premature self-declared PROVEN (its over-credit
  claws back at claim-terminal).
- A REFUTED status refutes even with a green gate (the gate only proves
  the refutation reproduced — the issue prices it 0.0).
- NEGATIVE + green gate = a reproduced proven-negative finding —
  terminal strength per the fact schema, real rule-out work. The ladder
  prices claim-contribution separately; the residual reconciles.
- **No evidence → 0.3, never 0.0**: an all-zero step stream is the
  degenerate signal this card exists to break; the step happened, the
  calibration corrects.
- `step_credit(items)` = mean of item credits (mixed evidence grades
  between the anchors).

## 3. Evidence quality (source_reliability, if available)

`item_credit = anchor × reliability_weight`, where the weight is the
ICD-203 Admiralty source-reliability letter of the fact's WORST
provenance credibility (A 1.0 → F 0.5, declared policy constants, not
fitted; letter absent → 1.0). Reliability modulates the anchor — it
never invents one (refuted stays 0.0 under an A1 letter).

## 4. The step bank (row shape + fold semantics)

`q_cells.observe_step_credit` shares the pending-dispatch match face
(`_match_pending_dispatch`, extracted from the #462 W5 settlement) and
appends a `source: "settlement"` row with `credit_kind: "step"`:

- admissible by the #705 rule (≠ "verification") and folded EXACTLY like
  solve credit — success += w·c, failure += w·(1−c) — so each step
  moves both Beta dimensions (0.3 provisional mass is transient; see §5);
- credit is clamped [0,1] at the append boundary like any observation;
- `step_ref` (the step_id) rides only the returned receipt, never the
  append-only log's column set beyond `credit_kind`.

## 5. The claim-terminal calibration (the algebra)

Read the operand from the SAME log the fold consumes —
`q_cells.step_credit_totals(ws, did) = (Σc, n)` over this identity's
step rows (never a parallel tally that could drift). The sums count
ONLY mass-admitted rows, mirroring the fold's D-678.4a admission:
credit == 0.0 (failure observation) and credits above the observation
band count; band-valued rows (0, band] banked no mass and count in
neither Σ nor n (clawing a band row back would subtract mass that was
never banked — the #712 independent review's finding, pinned by
`test_calibration_never_claws_back_band_valued_steps`). Branch on `n`:

- **n = 0 → legacy face**: `observe_settlement(did, r)` unchanged —
  byte-identical rows and fold arithmetic for pre-#712 claims.
- **n > 0 → calibration face**: one `credit_kind: "step_calibration"`
  row with SIGNED mass deltas from the pure `_calibration_delta`:

```
L      = clamp01(r)                       # the legacy rail clamp
target = (0, 0)      if 0 < L ≤ band_ceIl # D-678.4a information option
       = (L, 1 − L)  otherwise            # the legacy fold endpoint
Δsuccess = L_target − Σc
Δfailure = f_target − Σ(1−c)
```

  At γ = 1 the invariant is exact: cumulative mass after the residual =
  the step-less endpoint for the same ladder value — **the endpoint is
  independent of step count** (a 3-step and a 0-step claim with the same
  outcome fold identically). Over-credit (Σc > L) yields Δsuccess < 0 —
  the clawback; under-credit the top-up.

γ ≠ 1 note: deltas are computed from raw ledger sums (the issue's
formula) while the fold applies each row's γ weight, leaving an O((1−γ)·
age) residue under the adaptive schedule — accepted; the explicit γ = 1
calibration face is exact and is what the acceptance tests pin.

## 6. The fold's treatment of a calibration row

- admitted (contributes mass), keyed into the same cell by the shared
  match; `credit` = Δsuccess and `failure_delta` = Δfailure applied
  VERBATIM after the γ weight — outside the [0,1] clamp (the append
  boundary validates finite-only instead), outside the observation band,
  outside the Φ tiebreak;
- never fed to the γ schedule's EMA (`schedule.observe` is skipped): a
  residual is bookkeeping over already-observed outcomes, and a signed
  clawback would drag the adaptive γ off its declared range;
- `append_observation` refuses `failure_delta` on any non-calibration
  row (ONE warn) so the column has exactly one legal home.

## 7. Failure posture

Every new face is fail-open telemetry in the established mold: an
unmatched dispatch is the honest gap (warn, no fabricated bucket), a
scoring/banking exception inside `settle_step` is ONE warn that never
undoes the settled step, and `step_credit_totals` on an unreadable log
reports (0.0, 0) so settlement degrades to the legacy face instead of a
fabricated correction.

## 8. Named residuals

- A step settling AFTER its claim's terminal calibration (late
  SubagentStop) appends post-hoc mass the residual never saw — the #690
  sync barrier makes this ordering the rare crash shape; accepted,
  fail-open.
- Claim identity for `step_credit_totals` keys on claim/dispatch id only
  (the same identity the settlement matches); a harness dispatch id that
  never carried step rows behaves exactly as before.
- The strategy-store row keeps the LADDER value (claim truth), never the
  residual — the cross-task store records what the claim proved.
