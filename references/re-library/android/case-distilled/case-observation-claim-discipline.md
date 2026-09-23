---
name: case-observation-claim-discipline
description: 'Windowed observation and claim discipline on Android targets with stateful server
  behavior (case-distilled, internal campaign D1): exclusion protocols (static+dynamic zero-hit
  before a native-only conclusion), state-parity window comparisons, honest instrumentation-bug
  records, conclusion-strength gating, byte-level equality overturning variant theories, capability
  honesty ladders for acceptance reports, and confidence columns in mapping tables. Use when two
  sampling windows disagree, when writing a negative-capability or path conclusion, or when typing
  acceptance results.'
domain: android
family: case-distilled
source_id: D1
source_license: internal
retrieved: 2026-09-23
epistemic: evidence-derived
distill_bar: general+heuristic
dedup: new
campaign_cluster: E (I06-I11,I14,I15,I41,I48,I51,I58,I61,I62,I65,I67,I84,I85)
---

# Observation and claim discipline (case-distilled)

> Internal-campaign distillate (evidence-derived; provenance = D1 cluster E).
> verification-safety owns evidence-type vocabulary for state transitions;
> dynamic-observation-ladders owns channel choice. This card owns how windows,
> exclusions, and claims are TYPED — what a given observation is allowed to
> prove.

## Exclusion protocol

Verdict algebra:
`native-only conclusion ⇔ static zero-hit census ∧ dynamic zero-call count`,
`broken instrumentation ⇏ negative claim`. A negative-capability conclusion
(the signing path never touches the Java layer) requires the static census AND
the dynamic zero-call count over captured requests — either alone is a
hypothesis. And a broken reader (type-wrapper cast errors) downgrades every
conclusion that depended on it until re-measured; the honest-bug record stays
in the evidence file, not in a side channel.

## Window state parity

| Situation | Rule |
|---|---|
| identical tooling produced rich op-stream in window 1, near-nothing in window 2 | windows are compared only at STATE PARITY — record server/local cache state per window; divergence is state, not regression |
| the trigger is one-time (first-registration attestation) | record the trigger condition; forced reproduction is destructive → route around via the always-on parallel path (transport-write capture + static resolver read) |
| operator interaction available | use it: a UI event in-window is the reliable trigger for handshake-class protocol events |

Why parity matters more than tooling parity: the campaign's windows differed
by CACHE STATE, not by capability, and a naive read would have concluded
"protection engaged" or "tooling broke" — both wrong.

## Claim typing

| Claim about to be written | Allowed evidence | Not sufficient |
|---|---|---|
| "X never happens" (negative) | static census + dynamic zero-count + working instrumentation | one broken window |
| "X is computed entirely in custom code" (negative-space) | primitive-export census over a full window with zero hits on the target path | absence of obvious hits |
| "algorithm = textbook primitive" (or any equality claim) | byte-level equality across the full stage chain | structural similarity, variant-theory plausibility |
| "stage A output feeds stage B" (linkage) | same-window paired capture | separate-window plausibility |
| endpoint acceptance | declared dependency level + counts | pass counts alone |

Byte-equality overturn: the campaign's "custom hash variant" conclusions were
fully replaced when primitive-level hooks showed every digest stage matched
textbook implementations byte-for-byte. Structural similarity is a hypothesis
generator; equality is the only thing that settles an equality claim.

Cross-call divergence protocol: when block 1 replays byte-exact and later
blocks diverge — exclude context bytes, surrounding memory, chaining input,
call order by experiment; the LAST remaining variable is recorded as open
(register residue), WITH its blast radius (what it blocks: pure offline
re-derivation; what it does not: engine-path execution). An open variable
with a bounded blast radius beats a forced conclusion.

## Honesty ladders

Capability honesty ladder (for acceptance reports):
`achieved-level := hook-extracted < file-only < zero-device`; reports state
the achieved level by name, never describe level N as level N+1 — one
achieved level is one achieved level. A report saying "20/20 collected" is
incomplete without the level declaration (keys hook-extracted vs derived on
host).

Confidence columns: every header-to-mechanism or sample-to-structure mapping
table carries a confidence column — `high` only where runtime-verified,
`medium` where structure-only. Structural guesses harden into facts through
exactly this omission.

Conclusion-strength gate: a terminal claim ("signing is entirely native") is
written only when three dynamic windows + a static census + a call-chain read
all agree; otherwise it is written as an interim claim with the missing legs
named.

## Companions

[case-kill-evidence-counterplay.md](case-kill-evidence-counterplay.md)
(attribution discipline for kills),
[case-identity-channel-epistemics.md](case-identity-channel-epistemics.md)
(the elimination ladder this typing serves),
[verification-safety](../../method/process/verification-safety.md),
[loop-stage-gates](../../method/process/loop-stage-gates.md),
[falsifier-library](../../method/process/falsifier-library.md).
