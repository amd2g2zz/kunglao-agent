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
> and candidate scoring.

## Problem-type triage comes before route choice

Classify the target into one of a small set of problem types BEFORE choosing
an entry route — each type implies a different plan:

- standard signature / digest (regular output shape, named crypto
  primitives in source)
- hybrid encryption / key wrapping (asymmetric transport of a symmetric key)
- cookie / header / multi-parameter joint signing (several fields consume
  shared intermediates)
- bytecode-VM / heavy-obfuscation pure-algorithm (big arrays, dispatch
  loops, bitwise-dense state machines)
- binary-protocol (WASM / protobuf-class / WebSocket frames)
- challenge / risk-control parameter (environment and behavior enter the
  computation)

If the type is unclear, the blocking-point question disambiguates: wrong
entry found, raw string not aligned, intermediates not captured, runtime
dependencies missing, image vs parameter line entangled, or protocol
boundary unproven — each blocker names its own next move, and "which
blocker am I at" is a cheaper question than "which tool do I run".

## Writer→builder→entry→source decomposition

Enter at the FINAL WRITE POINT, never at a big obfuscated file: the last
place a value touches the outgoing request (send call, header setter, cookie
write, frame emit). Then decompose backward one role at a time: the writer
(consumes the finished value) ← the builder (assembles it from parts) ← the
entry (the function the page actually calls) ← the source (where each part
is born).

**Checkpoint discipline** — record FIVE layers as you go, so every later
comparison has an anchor:

1. writer checkpoint: the final URL / header / body / cookie / frame
2. builder inputs: query, payload, token, challenge material, trajectory,
   environment fields
3. the raw string / payload being encoded
4. intermediates: pre-encode arrays, sub-digests, padded blocks
5. the final output

**Intermediates before encoding.** Recover the intermediate values before
fighting the final encoding layer — mismatch hunts over five anchored layers
localize a wrong step immediately, while mismatch hunts over input/output
pairs only prove "something inside differs". This is the **first-deviation
walk** for any failing replay: walk raw input → concatenation → time/random
injection → intermediates → final output, and fix the FIRST layer that
diverges, not the symptom downstream of it.

## Challenge (captcha-family) decomposition

A challenge target is FIVE parallel lines, never one problem — decompose
before solving, because the lines have independent blockers:

1. initialization / challenge-issuance line (how the challenge is fetched,
   bound to the session)
2. image / prompt-recognition line (the perceptual problem, if any)
3. parameter-builder line (trajectory, distance, answer encoding)
4. environment / collector line (the fingerprint blob the verify call carries)
5. final verify line (the submit request and its joint parameters)

Entangling line 2 with line 3 is the classic stall: the geometry can be
solved while the verify still fails because line 4's blob was wrong. Gate
live verification on a **success baseline**: a handful of manually-produced
successful samples define what "success" looks like and calibrate the
solver; consecutive failures with no anomaly in any line trigger a
deliberate route switch (change the approach class), not another retry.

## Candidate scoring for entry discovery

When multiple functions claim to be the signer, score candidates on declared
dimensions instead of eyeballing: name match, source-keyword match, runtime
stack presence, request correlation (does it run when the request fires),
input/output flow match, module-export visibility, cross-source agreement,
and verification result. Evidence classes are stratified: a candidate is
"verified" only with at least one runtime-verification-class item, and a
"high confidence" label requires TWO independent evidence classes — name
plus keyword is never enough. Failed verifications are kept as negative
evidence; an entry-discovery ladder that exhausts (global search → component
registry → module cache → runtime hook → init-time hook → static AST →
source reimplementation) ends in an explicit unsupported verdict, not a
guess.

Companions: [web-re-quickref.md](../labs/web-re-quickref.md) (five-step
signature workflow), [web-risk-control.md](../risk-control/web-risk-control.md)
(backward endpoint tracing + challenge-bundle shapes),
[falsifier-library](../../method/process/falsifier-library.md) (kill
experiments per hypothesis family).
