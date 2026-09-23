---
name: external-algorithm-recovery-chains
description: 'Pure-algorithm recovery planning chains (external-distilled, S2/S3/S4): decompose from the
  final write point backward (writer→builder→entry→source) with five checkpoint layers, recover intermediates
  before final encoding, problem-type triage before route choice, captcha five-line decomposition, first-deviation
  diff walk for replay mismatch, candidate scoring with evidence-class requirements. When planning a signature,
  challenge-parameter, or encryption recovery task and deciding where to enter and what to capture.'
domain: web
family: external-distilled
source_id: S2,S3,S4
source_license: MIT,none,Apache-2.0
retrieved: 2026-09-23
epistemic: external-derived
distill_bar: general+heuristic
dedup: overlap(web-risk-control backward endpoint tracing)
---

# Algorithm-recovery planning chains (external-distilled)

> External-derived methodology (never directly PROVEN). Generalized paraphrase;
> provenance = S-id list above. Backward endpoint tracing (consume-point →
> producer, one hop per iteration) is web-risk-control's; this card lands the
> planning layer around it: triage, checkpoint structure, deviation walks,
> and candidate scoring. Advisory: it is planning doctrine, not proof —
> candidate verdicts still go through the evidence stratification below.

## Problem-type triage comes before route choice

Classify the target before choosing an entry route; if the type is unclear,
classify the BLOCKER instead — it is the cheaper question and each answer
names its own next move.

| Problem type | Signals | Route implication |
|---|---|---|
| standard signature / digest | regular output shape, named crypto primitives in source | capture → identify → offline replay (quickref five-step) |
| hybrid encryption / key wrapping | asymmetric transport of a symmetric key | locate key-unwrap first, payload cipher second |
| cookie / header / multi-param joint signing | several fields consume shared intermediates | checkpoint discipline (below), joint capture |
| bytecode-VM / heavy-obfuscation pure-algorithm | big arrays, dispatch loops, bitwise-dense state | jsvmp-triage lane, instruction-trace methodology |
| binary protocol | WASM / protobuf-class / WebSocket frames | imports/exports census, frame segmentation |
| challenge / risk-control parameter | environment + behavior enter the computation | five-line decomposition (below) |

Blocker vocabulary when type is unclear: `wrong-entry`, `raw-string-unaligned`,
`intermediates-uncaptured`, `runtime-deps-missing`, `image-vs-param-entangled`,
`protocol-boundary-unproven`.

## Writer→builder→entry→source decomposition

Enter at the FINAL WRITE POINT, never at a big obfuscated file. Decompose
backward one role at a time, capturing five checkpoint layers at every hop —
they are the anchors every later comparison stands on:

| Layer | Content |
|---|---|
| 1 writer | the final URL / header / body / cookie / frame |
| 2 builder inputs | query, payload, token, challenge material, trajectory, environment fields |
| 3 raw payload | the raw string / byte stream being encoded |
| 4 intermediates | pre-encode arrays, sub-digests, padded blocks |
| 5 final output | the finished encoded value |

**First-deviation walk** for any failing replay — why: mismatch hunts over
five anchored layers localize the wrong step; hunts over input/output pairs
only prove "something inside differs":

```text
for layer in [raw_input, concat, time_random_inject, intermediates, final]:
    diff(current[layer], expected[layer])
    on divergence: FIX THIS LAYER (not the downstream symptom); restart verification
```

## Challenge (captcha-family) decomposition

A challenge target is five parallel lines, never one problem — blockers are
independent, and entangling L2 with L3 is the classic stall (the geometry can
be perfect while the verify still fails because L4's blob was wrong):

| Line | Owns |
|---|---|
| L1 init/challenge-issuance | how the challenge is fetched, bound to the session |
| L2 image/prompt-recognition | the perceptual problem, if any |
| L3 parameter-builder | trajectory, distance, answer encoding |
| L4 environment/collector | the fingerprint blob the verify call carries |
| L5 final verify | the submit request and its joint parameters |

Verdict algebra for the live-verification gate:
`solver-ready ⇔ success-baseline (∼5 manual successes, per type ≥2) ∧ no open line anomaly`;
`consecutive failures ∧ no line anomaly → deliberate route switch` (change the
approach class), never another blind retry.

## Candidate scoring for entry discovery

When multiple functions claim to be the signer, score instead of eyeball:

| Dimension | Question |
|---|---|
| name / source keyword | textual match (weakest class) |
| runtime stack | does it appear on the live call path when the request fires |
| request correlation | does it run when the request runs |
| input/output flow | do shapes line up with the checkpoints |
| module-export visibility | reachable from the page's module graph |
| cross-source agreement | independent hints agree |
| verification | runtime verification result |

Verdict algebra:
`verified := ≥1 runtime-verification-class evidence item`;
`high := verified ∧ ≥2 independent evidence classes` — name plus keyword is
never enough. Failed verifications are KEPT as negative evidence. The
discovery ladder that exhausts (global search → component registry → module
cache → runtime hook → init-time hook → static AST → source reimplementation)
ends in an explicit `unsupported` verdict, not a guess.

Companions: [web-re-quickref.md](../labs/web-re-quickref.md) (five-step
signature workflow), [web-risk-control.md](../risk-control/web-risk-control.md)
(backward endpoint tracing + challenge-bundle shapes),
[falsifier-library](../../method/process/falsifier-library.md) (kill
experiments per hypothesis family).
