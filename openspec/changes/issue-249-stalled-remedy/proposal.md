# issue-249-stalled-remedy — STALLED routes to its own remedy

## Why

Field evidence (wbtest, 2026-09-12 — the agent's own diagnosis, issue #249
verbatim): the STALLED gate deadlocks its own remedy. The health flatline
clears only on real claim-state change; settling requires dispatch; the
rc=1 gate (`hooks/worker_budget_core.check_convergence_health`) blocks ALL
dispatches; and the recovery protocol ("reformulate or decompose") is
printed PROSE with no invokable channel. The docstring says "NOT a 'flag
and walk away' tool" — but the walk-away path was never wired. Owner
routing pin (2026-09-18): the primary remedy path is the decomposition
operator (issue-234 fan-out, merged as scripts/target_ladder.py); the
#203 anchor-backflow alternative is out of scope.

## What Changes

1. **Invokable remedy reference (detector face)**: the STALLED verdict
   JSON carries a `remedy` object (operator: decompose, the stuck claims,
   the remedy-declared dispatch marker, the target-ladder mint command),
   and the human action string carries the same literals. The recovery
   protocol is never prose-only again. SPINNING (rc=2) keeps its
   harder-stop semantics — out of scope per the issue.
2. **Remedy exemption (gate face)**: at the rc=1 STALLED face ONLY,
   `check_convergence_health` admits the gate's own prescribed remedy —
   a dispatch whose prompt carries the `remedy: decompose` marker AND
   whose target intersects detector state (mirror of the #237 D2
   verifier pass-through, single-sourced in hooks/lib_kunglao):
   - channel A — the target claim is in the STUCK set (dispatched but
     flat): the diagnosis / decomposition-execution dispatch;
   - channel B — the target claim is ABSENT from the flatlined trailing
     open set and register-OPEN AND its depends_on references a stuck
     claim (mint provenance — the split's sub-claims, operator-agnostic
     over #234/#241).
   The exemption is fail-closed on every unresolvable input (no claim id,
   lib outage, detector state unresolvable, register unreadable); legacy
   1-arg callers keep the exact prior block behavior; every other gate in
   the pre_check battery still applies to a remedy dispatch; SPINNING and
   the rc=4 fail-open crash semantics are untouched.
3. **Mechanical flatline break**: minting via the existing issue-234
   machinery (`scripts/target_ladder.py --mint`, `mint_sibling_claims`)
   registers OPEN sub-claims -> the next ledger entry changes open_count
   -> the flatline breaks -> the stuck parent retires (e.g. SUPERSEDED by
   its alternatives) -> the verdict flips HEALTHY -> ordinary dispatch
   resumes. Pinned end-to-end by a full-cycle test through the REAL
   detector CLI, the REAL pre_check battery, and the REAL mint.

## Out of Scope

- The #203 anchor-backflow reformulate channel (owner routing pin).
- SPINNING (rc=2) remedy routing / harder-stop semantics (separate
  judgment per the issue).
- The trajectory metric design (#129 owns loop-health) and the #241
  plan-granularity split face (`scripts/claim_granularity.py`, merged on
  its own branch, not yet in dev) — this change wires the MERGED #234
  fan-out as the decomposition operator.
- The verify/red-team provenance standard for settled claims (#237 D3
  owns it; the full-cycle test settles the parent SUPERSEDED, not PROVEN,
  to avoid the UNVERIFIED_EVIDENCE forgery surface).
