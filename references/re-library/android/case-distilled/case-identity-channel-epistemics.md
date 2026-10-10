---
name: case-identity-channel-epistemics
description: 'Device-identity and encrypted-channel epistemics for Android risk-control targets
  (case-distilled, internal campaign D1): component-elimination replay ladders, verdict-code
  stratification, signature-enforcement mapping per endpoint class, identity family keys that survive
  resets, envelope-key inference from stability observations, wrong-direction search death, and
  break-through-the-primitive-surface. Use when a server rejects requests unpredictably, when fresh
  identities fail while replayed ones pass, or when a key chain has one unexplained link.'
domain: android
family: case-distilled
source_id: D1
source_license: internal
retrieved: 2026-09-23
epistemic: evidence-derived
distill_bar: general+heuristic
dedup: new
campaign_cluster: C (I34-I37,I53-I57,I59,I60,I64,I76; community rows I69,I71,I75 marked in-card)
---

# Identity and channel epistemics (case-distilled)

> Internal-campaign distillate (evidence-derived; provenance = D1 cluster C).
> Sections marked `[community-claim]` carry public-source testimony — a
> separate epistemic class from the campaign's own experiments; they are kept
> adjacent, never merged. web-risk-control owns the web-lane doctrine; this
> card is the android-lane face with its own decision tables.

## The elimination replay ladder (soul table)

When a server rejects requests and the cause is unknown, run the ladder —
one factor removed per rung, against a capture that PASSES:

```text
rung 1  replay the passing capture verbatim on new transport   → isolates connection layer
rung 2  drop one signature-header group                        → isolates the signature set
rung 3  swap session material (cookies/credentials)            → isolates session binding
rung 4  drop channel headers (ticket/nonce/crypto markers)     → isolates the encrypted channel
rung 5  substitute the whole body (plaintext for ciphertext)   → isolates body-level policy
```

Verdict algebra:
`judged factor = the rung whose removal flips the verdict`;
`verdict codes are stratified first` — parameter-or-decrypt failure and
policy refusal are DIFFERENT server codes; classify the code before
diagnosing, because the two route to disjoint fixes (body construction vs
trust standing).

Why a ladder instead of hypothesis testing: each rung is one component,
removable without rebuilding anything, and the ladder's order is
cheapest-transport-first. The campaign's terminal verdict (the judged factor
was the encrypted body channel, not any signature header) took six table rows
and surprised everyone — signatures everyone had spent weeks on were not
checked on that endpoint class at all.

## Enforcement mapping (planning layer)

`signature enforcement is per endpoint class` — map it before planning any
delivery: config/scheduling/reporting surfaces commonly accept unsigned forged
identities; login/chat/completion enforce the risk chain. The enforcement map
is the first deliverable of the identity lane: it tells you which endpoints
can carry acceptance tests while the hard chain is still unbroken.

## Identity family keys

| Situation | Rule |
|---|---|
| fresh randomized identifiers still yield the old server identity | a family key survives resets — find the derived identifier that persists across app-data clear; identity is family-keyed, not id-keyed |
| reset recipe applied | delete the settings-identifier file AND its fallback copy together; a surviving fallback restores the old identity |
| planning identity reuse | record which identifier classes were randomized without effect — negative identity results are the family-key evidence |

## Channel anatomy reading + key-chain epistemics

Read an encrypted channel by its skeleton before any key work: handshake
(ephemeral exchange + self-signed proof) → server chain + ticket →
per-request stream-cipher bodies with client-random nonces → plaintext error
responses. The skeleton bounds what each key must do before you have any key.

| Situation | Action | Why |
|---|---|---|
| a session key survives restarts AND re-handshakes | infer envelope semantics: the peer holds the key and rewraps per handshake | stability observations are mechanism evidence without static proof — label the inference, do not promote it |
| one link of the key chain unexplained; internal offsets stalled | move to the primitive surface: hook the KEY-DERIVATION import on the crypto provider (a PLT import, not an internal offset) | the campaign's chain broke open exactly there after internal-offset work stalled; primitives receive the cleartext of every derivation |
| a large candidate space all failed (hundreds of unwraps) | STOP scaling; re-examine the direction assumption | the campaign's 500-candidate death was a ticket field the client NEVER unwraps — server-opaque by construction; the correct model dissolved the search |
| two stages' linkage unproven | capture both in the SAME cold-start window (pairing discipline) | single-stage captures leave the linkage forever unproven |
| handshake must be re-triggered | trigger with the first channel-tagged request (often needs real interaction); file removal alone is unreliable | trigger mechanics are stateful; the reliable trigger is the protocol event, not the filesystem |

`[community-claim]` Public testimony agrees with the campaign's own finding
that fresh-identity signing is bound to device-enrollment keys and that top
public work piggybacks on real-device sessions (enrollment binding, I69).

`[community-claim]` Published server-trust behavior (I71): new devices default
untrusted; trust accrues from fingerprint consistency, behavior streams, and
aging; enforcement escalates soft rate limit (success-status empty body) to
challenge to ban; high-frequency empty responses require backoff.

`[community-claim]` Byte-wise query binding (I75): treat as a fixture rule —
replay fixtures freeze COMPLETE URLs; changing any query parameter voids even
a correctly re-signed request.

## Companions

[case-emulation-campaign-discipline.md](case-emulation-campaign-discipline.md)
(the emulator route to the same keys),
[case-observation-claim-discipline.md](case-observation-claim-discipline.md)
(level-honesty ladder for acceptance reports),
[wire-format-recognition](../../method/formats/wire-format-recognition.md)
(opaque body triage), [web-risk-control](../../web/risk-control/web-risk-control.md)
(web-lane anti-bot doctrine), [rotation-characterization](../../dynamic/rotation-characterization.md)
(formalization for the keys that DO rotate).
