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
> in what order, and how to trust what the hooks report. Advisory: the ladder
> is discipline, not proof — a diff that only shows your own instrumentation
> is a failed intervention.

## The observe→intervene ladder

One question first: *what justifies touching the target's behavior?* Only a
RECORDED signal naming the target — never "it might detect us".

```text
// rung 1: passive-observe FIRST — response chain, request sequence, page scripts; zero hooks
//   (detection surface of passive observation is zero)
// rung 2: probe in RECORD-ONLY mode — anti-debug constructs, integrity checks,
//   environment reads, dynamic code, realm/loader activity; no patching
// rung 3: intervene ONLY on a recorded signal — time shifts, randomness forcing,
//   env overrides, debugger neutralization, scoped to the observed construct
// rung 4: diff baseline vs intervention — recorded events, requests, errors, side effects
//   rule: MORE events is NOT success; only the target request + business state count
// rung 5: widen only after the tapped build verifies against the original
//   (exceptions, requests, key outputs unchanged)
```

Compatible layering with the hook-early rule: passive-first applies to the
FIRST observation of a mechanism; once instrumentation is chosen, hooks still
install before the target code runs. Source taps stay conservative: narrow
property reads only, skip strings/comments/assignments/calls, verify the
tapped build before widening.

## Hook composition & persistence

| Situation | Rule |
|---|---|
| multiple probes on the same API | compose in LAYERS (second wraps first); overwriting is a defect |
| page reassigns a hooked API | reconcile: rebuild the chain on the new holder; reconcile FAILURE (not the reassignment) is the alarm |
| persistent hook on a not-yet-existing frame | status `pending` — a promise, never evidence of installation |
| frame indexes / element handles | snapshot-bound: die on navigation; use identity-bearing references (frame url/name, document identity) |
| session identity changed (nav/disconnect/suspend) | prior bindings AND results invalid: rebind, re-verify; never replay stale handles |

## Evidence budgets & completeness

Verdict algebra for the hook stream:
`evidence-grade ⇔ pending_drained ∧ body_states_resolved ∧ dropped == 0`,
with per-source budgets (first N events full, then sampled, per-source caps)
and the counting rule `suppressed_by_budget ≠ dropped` — conflating them
corrupts every "nothing was recorded" reading.

| Completeness field | Meaning | Fail rule |
|---|---|---|
| pending requests | stop does not wait for stragglers by default | undrained → capture incomplete |
| body_state | skipped / failed / truncated are not bodies | any unresolved → no body evidence |
| dropped counters | genuine event loss in the ring | >0 → evidence suspect |
| truncation layers | what was SAVED vs what was RETURNED | check BOTH before treating a body as complete |

Attribution humility: initiator stacks for same-URL concurrent requests are
match-confidence hints, not proof — corroborate by request identity, not URL
equality. A changed capture field is a lead, not an identified algorithm.

## Reading emptiness correctly

Verdict algebra for instrumentation reads:
`recorded_hit ⇒ positive evidence`; `empty ⇏ absence` (fixed-point coverage,
event caps, and process acknowledgement bound what "empty" means). Rules
that follow, each with its failure story:

| Anti-read | Correct read |
|---|---|
| "log is empty, the target never ran" | check the channel with the SAME world/frame identity the hook used; never cite an empty bounded log as absence proof |
| "trace-end values show what flowed" | values collected at trace END are a post-hoc snapshot, not at-event values — rotating values make them differ (rotation-characterization formalizes this); side-effecting reads may be value-skipped by design |
| "rewrite reported success, so the instrumented code ran" | rewrite success = transformation completed; confirm via runtime markers + actual log lines |
| "user expression failed, retry on the other world" | a failed expression is not retried on another channel — side effects may have fired; audit before re-firing. Page-owned globals/hooking → main world; neutral probing → isolated default |

Companions: [web-re-quickref.md](../labs/web-re-quickref.md) (hook/boundary
reference + injection order), [web-risk-control.md](../risk-control/web-risk-control.md)
(trigger→observe→attribute loop),
[rotation-characterization](../../dynamic/rotation-characterization.md)
(rotating-value formalization).
