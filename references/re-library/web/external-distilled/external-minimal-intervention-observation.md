---
name: external-minimal-intervention-observation
description: 'Observation and minimal-intervention discipline for instrumented web targets (external-distilled,
  S3/S4): observe-first ladder (intervene only on observed signals), baseline-vs-intervention diffing, layered
  hook composition with reconcile-on-overwrite, evidence sampling budgets (suppressed ≠ dropped), world/frame
  channel discipline, capture-completeness gates, hit ≠ miss asymmetry for fixed instrumentation points. When
  planning dynamic instrumentation on a target that may detect or defeat hooks, or when hook output looks empty.'
domain: web
family: external-distilled
source_id: S3,S4
source_license: none,Apache-2.0
retrieved: 2026-09-23
epistemic: external-derived
distill_bar: general+heuristic
dedup: new
---

# Minimal-intervention observation (external-distilled)

> External-derived methodology (never directly PROVEN). Generalized paraphrase;
> provenance = S-id list above. Our quickref owns WHERE to hook and the
> install-before-load rule; web-risk-control owns the trigger→observe→
> attribute loop. This card owns the intervention POSTURE: how much to touch,
> in what order, and how to trust what the hooks report.

## The observe→intervene ladder

Instrumentation itself is an intervention with detection cost. Climb it
deliberately:

1. **Observe passively first.** The FIRST look at an anti-bot mechanism uses
   no hooks at all — read the response chain, the request sequence, the page
   scripts. Passive observation has zero detection surface.
2. **Probe in observe mode.** When instrumentation starts, the first probes
   only RECORD: anti-debug constructs, integrity checks, environment reads,
   dynamic code, realm/loader activity. No patching, no behavior change.
3. **Intervene only on an observed signal.** Mode changes (time shifts,
   randomness forcing, environment overrides, debugger neutralization) are
   justified exclusively by a RECORDED signal that names the target — never
   "it might detect us". Interventions stay minimal and scoped to the
   observed construct.
4. **Diff baseline vs intervention.** Compare recorded events, requests,
   errors, and side effects between the two runs. An increase in recorded
   events is NOT success — only the target request and business state count
   as the outcome. A diff that only shows your own instrumentation is a
   failed intervention.
5. **Conservative source taps before broad rewrites.** When source-level
   instrumentation is needed, tap narrowly chosen property reads only, skip
   strings/comments/assignments/calls, and verify the tapped build against
   the original on exceptions, requests, and key outputs before widening.

Compatible layering with the hook-early rule: passive-first applies to the
FIRST observation of a mechanism; once instrumentation is chosen, hooks still
install before the target code runs.

## Hook composition & persistence

Multiple probes on the SAME API must compose in layers, not overwrite:
second registration wraps the first; an external reassignment by the page
triggers a reconcile (rebuild the chain on the new holder) — and reconcile
failure, not the reassignment itself, is the alarm. Persistent hooks survive
navigation; their registration on a not-yet-existing frame is "pending", not
"installed" — pending is a promise, never evidence. Snapshot-bound references
(frame indexes, element handles) die on navigation; identity-bearing
references (frame URL/name, document identity) are the durable form, and any
session-identity change invalidates prior captures: rebind and re-verify,
never replay stale handles.

## Evidence budgets & completeness

- **Sampling budgets keep the signal.** Unbounded high-frequency hooks
  (prototype getters, hot APIs) evict the rare events that matter. Budget
  the stream: first N events per source recorded in full, then sampled, with
  per-source caps. Suppressed-by-budget and genuinely-dropped are DISTINCT
  counts — conflating them corrupts every "nothing was recorded" reading.
- **Capture completeness gates.** A capture is evidence only when its
  completeness fields say so: pending requests drained (stop does not wait
  for stragglers by default — check), body states resolved (skipped /
  failed / truncated are not bodies), dropped counters at zero. Two
  truncation layers exist (what was SAVED vs what was RETURNED) — check both
  before treating a body as complete.
- **Attribution humility.** Initiator stacks for same-URL concurrent
  requests are match-confidence hints, not proof; corroborate by request
  identity, not URL equality. A changed capture field is a lead, not an
  identified algorithm.

## Reading emptiness correctly

- **Hit ≠ miss asymmetry.** Fixed instrumentation points prove presence only:
  a recorded hit is positive evidence; an empty result is NOT evidence of
  absence (fixed-point coverage, event caps, and process acknowledgement all
  bound what "empty" means). Check the channel with the same world/frame
  identity the hook used, and never cite an empty bounded log as proof
  something did not run.
- **Snapshot ≠ at-event.** Values collected at trace END are a post-hoc
  snapshot, not the value at event time — rotating values make the two
  different (our rotation-characterization card is the local formalization).
  Value capture on side-effecting reads is skippable by design.
- **Rewrite success ≠ execution.** A source rewrite reporting success means
  transformation completed, not that the instrumented code ran — confirm via
  runtime markers and actual log lines before building on it.
- **Channel discipline.** Evaluate in the page's main world when reading
  page-owned globals or hooking page functions; the isolated default is for
  neutral probing. A failed user expression is not retried on a different
  channel — side effects may have fired; audit before re-firing.

Companions: [web-re-quickref.md](../labs/web-re-quickref.md) (hook/boundary
reference + injection order), [web-risk-control.md](../risk-control/web-risk-control.md)
(trigger→observe→attribute loop),
[rotation-characterization](../../dynamic/rotation-characterization.md)
(rotating-value formalization).
