---
name: case-constant-fingerprint-attribution
description: 'Constant-fingerprint algorithm attribution and whitebox identification for Android
  native libraries (case-distilled, internal campaign D1): movz/movk constant reconstruction as an
  algorithm fingerprint, absence triangulation (no standard constants + no crypto imports = custom),
  whitebox table-driven cipher identification, differential fault analysis workflow with fault-width
  discipline, and runtime-random pinning for reproducible restoration. Use when a recovered function
  computes an unknown digest or cipher, when constants do not match any standard algorithm, or when
  an offline rewrite diverges across calls.'
domain: android
family: case-distilled
source_id: D1
source_license: internal
retrieved: 2026-09-23
epistemic: evidence-derived
distill_bar: general+heuristic
dedup: overlap(unidbg-algo-recovery constant-search traps)
campaign_cluster: F (I27,I28,I49,I50; community row I73 marked in-card)
---

# Constant-fingerprint attribution (case-distilled)

> Internal-campaign distillate (evidence-derived; provenance = D1 cluster F).
> unidbg-algo-recovery owns the constant SEARCH traps (endianness, split
> constants, shared-IV ambiguity) and output-length priors; this card owns
> what to DO after the constants are in hand: class the algorithm, or class
> its protection.

## Constant census as fingerprint

```text
1. scan the candidate function for paired load-immediate/shift instructions
2. rebuild the 32-bit constants                    # movz/movk pairs
3. read the multiset:
     standard digest round-constant prefix         → that standard digest (locate by
                                                     first-constants-in-order inline)
     table addresses + round-count field           → whitebox-class block cipher
     dense state-code multiset                     → flattened FSM (see dispatch card)
     none of the above, no crypto imports library-wide
                                                   → custom construction
```

Absence triangulation rule:
`custom construction ⇔ no standard-constant hit inside the function ∧ no
standard crypto import at library level`. Either alone is a guess — a library
can import what the function avoids, and a function can inline what the
library also imports.

## Whitebox identification + DFA workflow

| Signal | Reading |
|---|---|
| table-driven rounds, no plaintext standard constants anywhere in the binary | whitebox: round keys fused into lookup tables — a constant search CANNOT succeed; stop searching |
| round count stored in the context structure | confirm before planning fault rounds |
| decryption direction suspected | match the fault differential pattern against the decrypt-mode table of the recovery tool |

Differential fault analysis workflow (the campaign recovered the equivalent
key with it):

```text
1. instrument the LAST-ROUND input (round 9 of 10) — inject a single-byte
   fault on the low 32 bits
2. keep the 64-bit HIGH WORD INTACT                 # polluting high bits produced
                                                    # an unusable differential set once
3. collect >= 4 faulty ciphertexts per differential group, output at the
   block-completion point; normal output from an unfaulted run
4. run the recovery tool over grouped samples
5. validate: recovered key reproduces the observed outputs
```

`[community-claim]` For cross-run reproducible restoration of packet
signatures: pin EVERY runtime random source (the campaign's community source
names three distinct ones feeding one packet) — the hook plan exists to fix
randoms, not just to observe them.

## When the fingerprint says "custom"

Custom core recovered statically: the multiset above (block shape + key
length + output shape) classes it (e.g. unrolled ARX/Feistel family) — the
class label stays a HYPOTHESIS until a rewrite reproduces observed output
byte-for-byte. Byte-equality is the only family verdict (see
[case-observation-claim-discipline](case-observation-claim-discipline.md)).

## Companions

[case-hardened-dispatch-recovery.md](case-hardened-dispatch-recovery.md)
(where the constant multisets come from),
[unidbg-algo-recovery](../emulation/unidbg-algo-recovery.md) (constant-search
traps + output-length priors),
[falsifier-library](../../method/process/falsifier-library.md) (kill
experiments per algorithm-family hypothesis).
