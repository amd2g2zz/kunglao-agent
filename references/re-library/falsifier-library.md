---
name: falsifier-library
description: Hypothesis-family to falsification-experiment library — for the recurring reverse-engineering hypothesis families (digest family, HMAC structure, block-cipher mode, protobuf body, signing entry point, absent network capability, native-standard algorithm, fact conflict, async entry point, obfuscation variant) this card lists the kill experiments: the trigger to run and what the positive and the negative outcome each prove. Use when registering a candidate in the hypothesis layer (every candidate must enter with a named falsifier), when an open hypothesis has stalled without an executed experiment, or when choosing the one experiment that discriminates two competing candidates.
---

# Falsifier Library (hypothesis family → kill experiment)

Every candidate entering the hypothesis layer names its falsifier at
admission — a hypothesis that cannot say what would kill it is an opinion,
not a candidate. This card is the pattern library: the recurring hypothesis
families, and for each the experiments whose outcomes are interpretable in
BOTH directions. Notation: `trigger → ✓ what a positive proves / ✗ what a
negative proves`. A fired kill experiment is a finding either way
(`refuted` is a first-class hypothesis state, symmetric with `confirmed`).

## When to Use

- Registering a candidate: pick its falsifiers from the matching family
  row BEFORE the candidate enters the store (admission gate).
- An open hypothesis has stalled with no experiment run — execute the row.
- Two candidates compete: choose the experiment whose two outcomes split
  them; if none can, they are one candidate written twice.

## The falsifier table

| Hypothesis family | Falsifier experiments (trigger → ✓ / ✗) |
|---|---|
| **1. Signature is MD5/SHA-family digest** | (a) Reference implementation across serialization candidates (raw, sorted key=value, url-encoded, trailing-newline variants) replayed on captured pairs → ✓ family + the actual serialization; ✗ nothing yet — modified implementation suspected, proceed to (b). (b) Canonical IV / round-constant block byte-search in the boundary binary → ✓ native-family support; ✗ custom digest in standard clothing — extract the real constants. (c) Avalanche probe (flip 1 input byte; expect ≈ half the output bits to flip) → ✓ digest-class diffusion; ✗ checksum / CRC / non-avalanching transform. |
| **2. HMAC(secret ‖ payload)** | (a) Key-origin trichotomy observation — hardcoded literal, server-delivered field reused as key, device/install-derived; each origin has a distinct observation channel (constant hunt / response capture / derivation trace) → ✓ origin pinned; ✗ per-origin absence reopens the other two, it does not close the family. (b) Hash length-extension feasibility (few-shot below): if the secret PREFIXES the payload and the digest is native MD5/SHA-1/SHA-256, a forged extension must be accepted → ✓ proves structure AND native family in one shot; ✗ the secret does not prefix, the digest is non-native, or an HMAC wrapper sits on top. |
| **3. Block cipher, AES-ECB/CBC-class** | (a) Block-independence probe: fixed key, flip one byte of plaintext block k, recapture → ✓ only block k changed = ECB-class; downstream blocks changed = chaining / stream / custom. (b) Canonical S-box (and inverse) presence in the binary → ✓ AES-family support; ✗ table-less or non-AES cipher. (c) Padding-oracle probe: does a corrupted ciphertext yield a distinguishable decrypt error (different code, message, or timing)? → ✓ oracle exists — an exploit lever plus proof the app decrypts in-process; ✗ uniform failure = no oracle. |
| **4. Response body is protobuf** | (a) Whole-body wire-type parse consuming exactly to the end with no overrun → ✓ structural support; ✗ not protobuf at this root (encrypted or framed wrapper — retriage, do not force-parse). (b) Wire-type-2 fragments decode as plausible strings (printable, domain/word-like) → ✓ schema-less decode on track; ✗ wrong root, or the length-delimited payloads are bytes. (c) Nested type-2 payloads recurse as legal messages consuming exactly their declared length → ✓ nested message; ✗ bytes field or an extra wrapper layer. |
| **5. Function X is the signing entry** | (a) Correlation under variation: hook X across multiple live requests; hook I/O correlates with the live field sample-by-sample → ✓ strong support; hook silent on live traffic = wrong entry. (b) Call-stack membership: X's stack passes through request-construction / business frames → ✓ in the path; timer- or idle-unrelated frames = coincidence. (c) Isolated-invocation fingerprint: invoke X with a controlled input; output equals the live field for that input → ✓ direct verification; ✗ a helper, not the entry. High confidence = network evidence + matching algorithm event + call stack, all three together; any two alone stay provisional. |
| **6. Target has no network capability** (capability-claim family) | A clean import table / call surface is a dynamic-resolution SUSPICION trigger, not a negative conclusion. Experiment: enumerate APIs resolved at runtime (dlsym/GetProcAddress-class results, in-memory stubs, re-bound slots) → ✓ memory-dirty: claim falsified; ✓ memory-clean within the exercised window: claim confirmable — state the window, it is bounded. Static-clean alone proves nothing either way. |
| **7. Algorithm is a native standard implementation** | (a) Byte-level constant compare (IV, S-box, round constants) against canonical tables → ✓ identical: standard support; any drift: modified variant — extract the actual tables from the binary. (b) Behavioral fingerprint (digest length, truncation, single vs double application) → ✓ canonical shape; ✗ modified implementation — which is the NORM: swapped IVs, mutated tables, truncated or double-applied digests, custom alphabets. Shape labels the hypothesis; only the constant/behavior compare labels the implementation. |
| **8. Two facts conflict; A is right** | (a) Independent re-derivation of BOTH facts from raw evidence WITHOUT reading either conclusion → the survivor wins; both die = a third position exists that neither captured. (b) Controlled-variable replay: shared input, exactly one variable switched between the two fact contexts → ✓ isolates which condition actually produces the observed output; ✗ both reproduce = the facts were never in conflict, only differently scoped — record scope, not a winner. |
| **9. Async entry point (crypto.subtle / Promise-class)** | (a) Then-able probe: treat EVERY returned value as possibly-thenable regardless of source-level async markers (transpilers and bundlers lie) → ✓ resolves to bytes: async path confirmed; ✗ rejects or returns a raw value: sync path or wrong entry. (b) Return-shape probe: ArrayBuffer / Uint8Array / hex string / base64 string — probe, never assume; each shape serializes differently downstream. (c) Timing probe: value available at call return = sync; materializes in a later microtask = async. |
| **10. Hardening/obfuscation variant judgment** | Discrimination cues: dispatcher shape (loop + state variable + indirect branch), state-constant range (dense 0..N = flattening-class; sparse wide jumps = VMP-class), handler-table layout. Falsifier: single-step a few state transitions and check the progression against the claimed variant's predicted shape → ✓ keep the label; ✗ re-classify BEFORE any countermeasure work. The judgment itself carries a falsifier because the wrong variant makes every downstream countermeasure wrong (devirtualizing a VMP as flattening burns days). |

### Few-shot — length-extension feasibility, family 2 (synthetic)

```python
# captured: 32-hex signature over unknown key || payload (SHA-256 shape).
# H(secret || payload) with a native Merkle-Damgard hash is extendable
# WITHOUT knowing the secret:
orig   = b"sid=7f3a&ts=1717000000"            # captured payload
suffix = b"&admin=1"                          # payload we want signed too
forged_sig = length_extension(                # glue padding + carry state
    digest=captured_sig,
    secret_len=SECRET_LEN_GUESSES,            # brute the block padding offset
    suffix=suffix)
# replay the forged pair (orig || suffix, forged_sig):
#   accepted  -> secret-prefix structure + native SHA-256, BOTH confirmed
#   rejected  -> secret does not prefix, digest non-native, or HMAC-wrapped
#                -> family 2 dies; re-enter at family 1 row (b)
```

### Few-shot — then-able probe, family 9 (synthetic)

```js
// source shows no `async` marker; trust nothing — probe the return value:
const r = Suspicious.sign(payload);        // what actually came back?
isThenable(r)                              // .then callable? probe, don't read
  ? r.then(b => dump(b, probeShape(b)))    // async path; normalize the shape
  : dump(r, probeShape(r));                // sync path
// probeShape decides ArrayBuffer vs typed array vs hex/base64 string —
// assuming the wrong shape corrupts every downstream serialization step.
```

## Closure summary

| Gate | Minimum evidence |
|---|---|
| Candidate admitted | A named falsifier per candidate — one without an entry does not enter |
| Family labeled | At least one falsifier executed with positive AND negative outcomes pre-stated |
| Competitors split | The chosen experiment's outcome refutes one side (or dissolves the conflict per family 8) |
| Refuted / confirmed | The kill experiment fired either way — recorded as a finding, routed via the evidence-type vocabulary |

## Cross-references

- Output-shape falsifier table behind families 1 and 3:
  [native-sign-recovery.md](native-sign-recovery.md#closure-summary)
- Protobuf-class parse loop behind family 4:
  [wire-format-recognition.md](wire-format-recognition.md#protobuf-class-parsing-without-a-schema)
- Three-of-two variant discrimination behind family 10:
  [jsvmp-triage.md](jsvmp-triage.md#three-feature-thresholds)
- Flattening/VMP countermeasures once the variant is confirmed:
  [anti-analysis.md](anti-analysis.md#control-flow-flattening-advanced)
- Which evidence type may update what after a falsifier fires:
  [verification-safety.md](verification-safety.md#evidence-type-vocabulary)
