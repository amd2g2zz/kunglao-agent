---
name: rotation-characterization
description: "Discriminating-experiment protocol for rotating runtime values (keys, tokens, session ids, nonces, cookies) — the four templates that turn 're-hook and it works again' into a characterized rotation: derivation-point hook (where the value is BORN), T / T+delta in-session double capture (bounds the rotation period), the trigger-isolation matrix (per-process vs per-session vs per-request vs timer), and rotation-input source trace (seed/nonce provenance). Mandatory reading for any dispatch on a rotation-flagged claim (runtime_value_rotation fired); the dispatch gate rejects a re-hook-only retry that does not carry `rotation-experiment: rotation-characterization`."
domain: dynamic
family: rotation
---

# Rotation Characterization (rotating runtime values → the discriminating experiment)

A rotating key is the loop-eats-itself failure: every individual cycle is
locally successful (hook → capture K1 → decrypt → works; later → fails →
re-hook → capture K2 → works again), so no single observation is ever
"wrong" and no contradiction is ever filed. The meta-fact — the value
ROTATES — is mechanically derivable (same claim slot, distinct value
fingerprints, issue #341), but it is only the START: knowing THAT the key
rotates is not knowing WHEN, WHY, or FROM WHAT. That is this card's job.

## When to Use

- `runtime_value_rotation` fired for one of your claim's subject slots
  (see `runs/.rotation-induction.json` / the hypothesis the induction
  filed) — the dispatch that works this claim MUST carry the marker
  `rotation-experiment: rotation-characterization`, and this card is the
  template it names.
- You observe the signature yourself, before any gate: the same
  extraction succeeded twice with byte-different values. Stop re-hooking;
  characterize instead.
- NOT for: stable values (no distinct fingerprints = no rotation premise),
  or values that fail identically every time (that is a wrong-value
  problem, not a rotation problem).

Standing rule (replay-vs-generalization doctrine): a captured value that
works ONCE proves nothing about the value being static. Replaying a
captured key/request does not count as done — fresh-input is the master
oracle. Until the four templates below say otherwise, the slot's honest
state is UNKNOWN-DYNAMIC, never "confirmed".

## Template 1 — derivation-point hook (where the value is BORN)

Hook the USE-point (the decrypt call, the request signer) and you re-run
the same cycle forever: you see K1, K2, K3 … with no structure. Hook the
BIRTH-point instead — the moment the value comes into existence:

- KDF-shaped birth: `CryptDeriveKey` / `BCryptDeriveKey` / `PBKDF2` /
  `HKDF` / `EVP_KDF` — hook the derivation, log (salt, info, iterations,
  base secret pointer) per call. A fresh call per value = derivation-time
  rotation with the inputs in your hand.
- Import/parse birth: the value arrived from OUTSIDE (config blob, server
  response, license file, `GetEnvironmentVariable`). Break on the parse
  site; the rotation is a DELIVERY property — go after the source
  (template 4), not the consumer.
- RNG birth: birth-site stack passes a CSPRNG (`BCryptGenRandom`,
  `CryptGenRandom`, `rand`/`mt19937`): per-instance randomization.
  Confirm by correlating two births — unrelated bytes = per-launch random,
  and the "rotation" is really "regeneration on restart".

✓ birth-site found: every observed value has a birth record; the hook
survives across two distinct values (it fires AGAIN for K2).
✗ use-point-only instrumentation is what got the loop stuck — a birth-site
that never fires under your trigger means the value pre-exists the
harness; widen to the module load / process start window.

## Template 2 — in-session double capture T / T+Δ (bounds the period)

Same process, same session, two captures separated by Δ:

```
capture(T)   → fingerprint K1 (sha256 of the value — never the raw bytes)
capture(T+Δ) → fingerprint K2
K1 == K2 → rotation period > Δ (double Δ and repeat)
K1 != K2 → rotation period ≤ Δ (halve Δ and repeat)
```

Bisection on Δ gives the rotation period in log steps. Record each
capture as a fact with `captured_at` — the induction's series is the
evidence this template grows. Practical bounds: start at Δ = the observed
failure latency (the gap between "worked" and "failed" in the field
loop); floor Δ at the request cadence (a value cannot rotate faster than
it is consumed) and ceiling at process lifetime.

✓ a bounded period (or a stable-across-session result, which is itself a
finding: rotation is per-session, see template 3).
✗ unbounded drift with no stable pair — check you are capturing THE value
and not a re-encoding of it (hex vs raw vs base64 of the same key produce
different fingerprints; normalize before fingerprinting).

## Template 3 — trigger-isolation matrix

WHAT makes it rotate? Four candidate triggers, each isolated by holding
the other three fixed:

| Hold fixed | Vary | Rotation observed → trigger class |
|---|---|---|
| same process, same session | one request/call | **per-request** (stateless server-side binding; the value is a nonce/receipt) |
| same process | new session/login | **per-session** (bound to auth lifecycle; re-login mints a fresh value) |
| same session | new process | **per-process** (derived from process-local entropy — PID, ASLR-adjacent seed, instance GUID) |
| everything fixed | wall-clock wait | **timer** (periodic regeneration; template 2's Δ gives the period) |

Run the matrix as four experiments, not one: the rows are falsifiers, and
the cell where rotation STOPS is the binding. A per-process result
collapsed into a per-request claim is the classic mischaracterization —
it survives single-process testing and dies in every multi-process
deploy.

✓ exactly one cell explains the field observations; file the fact with
the matrix as evidence.
✗ two cells both show rotation — nested triggers (timer AND per-request);
report the composition honestly rather than forcing one label.

## Template 4 — rotation-input source trace (seed/nonce provenance)

For derivation-time rotation (template 1, KDF birth): the rotation is
deterministic IF its inputs are. Trace each derivation input to its
origin:

- time-derived (unix ts, tick counter): rotation is reproducible given
  the clock — replay with the recorded timestamp.
- counter/sequence: value N+1 from N — the series is walkable, and
  future values are predictable.
- external seed (server nonce, config field): the source is the real
  authority; hook or pin the seed channel to control the rotation.
- pure entropy: unpredictable by design — stop chasing prediction; the
  deliverable is the birth-site hook + fresh-capture protocol, not the
  next value.

Provenance decides the finish line: a predictable rotation means the
analysis can GENERATE the next key (strongest close); a random rotation
means the analysis must OBSERVE each key (the honest close is the
protocol, not a value).

## Recording the characterization

- Every capture lands as a fact: `source:` runtime-observation family,
  `temporal_scope: runtime`, `subject_slot: <slot>`, `value_fingerprint:`
  sha256 of the NORMALIZED value, `captured_at:` ISO ts. Fingerprints
  only — raw key material never enters facts, notes, events, or the
  ledger.
- The trigger-matrix verdict updates the rotation hypothesis
  (`hypotheses/<id>.md`) toward confirmed/refuted with the experiment as
  evidence.
- The synthesis note (pending) the induction wrote is the ledger of the
  series; supersede it (never overwrite) when the characterization
  concludes.
