# design — issue-680-tier-contract

## The two tier axes, and why the gate checks one of them

- `priority_ratio.action_tier(claim) = min(eta+1, 3)` — the ATTEMPT
  HISTORY axis: the next tier this claim is ALLOWED at, given what has
  been attempted. What `check_tier_gate` prices; what the envelope's
  `tier` must match.
- `tier_rules.tier_for_claim(claim)` (#241) — the WORK-FEATURE axis:
  what tier the claim's verification intent REQUIRES (VM/dynamic -> T3,
  static-depth -> T2, else T1). Advisory (recall_inject); a claim can be
  ALLOWED at T2 but genuinely need T3 work — the ladder then climbs
  eta=1 -> 2 across dispatches.

Conflating them would recreate the deadlock from the other side (a T3-
requiring claim whose history says T1 would be permanently rejected).
This card binds the envelope to the ATTEMPT axis only.

## D-680.1: eta write timing — dispatch-time (attempted) vs settle-time

**Ruling: dispatch-time.** `_write_eta_at_dispatch` raises
`evidence_tier_attempted` to `max(eta, tier)` at the ALLOW tail, BEFORE
the worker runs.

Why dispatch-time wins:

- **The field's name is the contract.** `evidence_tier_attempted` — the
  tier ATTEMPTED, not PROVEN. A settle-time write would make it a
  success-ladder, renaming the invariant `check_tier_gate` enforces
  (eta >= tier-1 as a precondition for the NEXT tier) into something
  only success advances.
- **The deadlock this card fixes is a dispatch-time deadlock.** C-007
  could not be dispatched at all — no worker ever ran, so no settle
  event ever fired. A settle-time writer is invisible to the very
  failure it exists to fix.
- **A silently-dead worker must not re-deadlock the ladder.** With
  settle-time semantics, a worker that hangs/dies without settling
  leaves eta unclimbed; the next deeper dispatch hits the same
  gate-reject loop. Dispatch-time charging treats the ATTEMPT itself as
  the resource spend (pass@k / #604 already price re-dispatch cost).
- **Monotonic max() bounds the abuse.** Inflating eta with no-op
  dispatches costs one real (gated, worker-count-limited, deadline-
  bounded) dispatch per step, and no re-dispatch can LOWER attempt
  history; #604 MAX_RETRIES caps the same (worker, claim) spam at 3.

**Rejected alternative — settle-time write** (eta raised only on a
settled outcome): honest in isolation, but leaves the C-007 class
permanently undispatchable (nothing ever settles a tier the gate
refuses to dispatch) and couples the register writer to the settlement
parser's availability.

**Rejected alternative — derive-and-overwrite** (the gate silently
rewrites the envelope's tier): removes the LLM's ability to record a
deliberate deviation and hides the mismatch instead of making it
visible. REJECT-with-correct-value (same as #310/#496) keeps the
deviation discipline uniform across gates.

## Gate placement: tiercons BEFORE tier

On the C-007 shape (declared tier=2, eta=0) BOTH gates reject: tiercons
(envelope != action_tier) and the ladder gate (eta < tier-1). tiercons
runs first because its message is the actionable one ("re-dispatch with
tier=1" — a concrete value) while the ladder gate only states the
invariant. When the envelope is CONSISTENT but another open claim lags,
only the ladder gate fires — the breadth-first invariant is untouched.

## Deviation escape hatch

`agent-reasoning:` in the dispatch prompt records the mismatch (stderr
`TIER (deviation recorded)` + allow) — the identical contract as the
agenttype (#310) and top-1 (#496) deviation faces: a deviation is
allowed, but it must be RECORDED, never silent. This matters for the
work-feature axis: a claim whose work genuinely needs T3 while its
history says T2 dispatches with the recorded reasoning instead of
deadlocking.

## Verifier-remediation pass-through (the #237 D2 mirror)

tiercons is SKIPPED for verifier-remediation dispatches — a
kunglao-redteam / verdict-scorer dispatch for a PROVEN claim, resolved
by the same single-source predicate (`lib_kunglao.
is_verifier_remediation_dispatch`) the drift-gate pass-through uses. A
verifier's tier is not the claim's evidence-ladder step (the verifier
re-derives evidence independently), so binding it to `action_tier`
would gate the remediation on the very ladder the remediation exists to
repair — the #237 D2 lesson: a second gate blocking the honest
remediation path re-creates the deadlock class the pass-through exists
to prevent. The skip is wired at the call site (`pre_check`), not inside
the check, so the gate stays a pure tier-vs-history comparison.

## Test surface

Unit: the consistency gate (mismatch / match / deviation / uncheckable
shapes / verifier skip), the eta writer (raise / monotonic no-op), the
rank_feeds additive key, `Action.to_dict()` tier. Chain: pre_check
end-to-end — the C-007 acceptance-claim shape dispatches at its
computed tier instead of self-deadlocking; the ladder scenario
(consistent envelope, other claim lagging) still REJECTs.
