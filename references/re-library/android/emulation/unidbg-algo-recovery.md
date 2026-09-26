---
name: unidbg-algo-recovery
description: Discrimination and verification moves for native algorithm recovery that runs THROUGH the emulator — orient the constant search by output-length priors (including the asymmetric face where modulus-length blocks point at RSA-class), the three constant-search traps (endianness, ARM64 movz/movk split constants, shared-IV ambiguity), a five-posture key-provenance ladder, the bignum modular-exponentiation choke point for RSA-family capture, signature-reuse detection (establish that the signature is computed at all before recovering it), and the emulator-as-verifier move with failure-class triage and stack-reading discipline. Use when the algorithm family is still ambiguous, a constant byte-search keeps missing, the key's origin is unknown, or the rewrite needs a cheaper oracle than device round-trips. Not for the boundary-first ladder and its closure gate (native-sign-recovery owns the six-step ladder), not for the falsifier experiments behind family labels (falsifier-library families 1/2/7), not for the environment-answer filling the harness consumes (unidbg-env-filling).
domain: android
family: emulation
---

# unidbg algo-recovery (discrimination + verification moves, emulation half)

native-sign-recovery owns the boundary-first ladder — six ordered steps to
byte-equal reproduction — and unidbg-env-filling owns the environment
answers the harness consumes. This card carries the discrimination and
verification moves that run THROUGH the emulator: which family, which
constant, which key posture, is the answer right. Nothing here re-states
the ladder; every move feeds a ladder step.

## When to Use

- The family label is still ambiguous and the next discriminator must be
  cheap (a length prior, not a decompile).
- A constant byte-search over the binary keeps missing a constant the
  algorithm provably uses.
- The key's origin is unknown and the origin decides the capture channel.
- The rewrite keeps failing replay and the oracle cycle is too slow.

## Family orientation by output length (priors, not conclusions)

**Family: length-prior orientation (native-sign-recovery step-3 vocabulary)**

The digest-shape table (32/40/64 hex) lives in native-sign-recovery step 3
— do not duplicate it here. The delta face is the ASYMMETRIC prior: output
lengths that no digest produces.

| Output length (bytes) | Prior | Next discriminator | Evidence to capture | Variant inspiration |
|---|---|---|---|---|
| 16, digest-encoded | MD5-class digest | decode-to-16 + reference match + avalanche probe (below; falsifier family 1) — length orients, the reference match concludes | Output block + probe rate | Length priors orient the constant search — they never conclude it |
| 32, digest-encoded | SHA-256-class digest | documented IV/round-constant compare, then reference match | IV/constant match site | Same ladder, one rung down |
| 64 | RSA-512-class modulus OR SHA-512 digest | charset decides: hex = digest face; binary block ≡ 64 bytes = modulus face — then constant-search the modulus (below) | Block bytes + charset read | One length, two families — charset is the second discriminator |
| 128 | RSA-1024-class modulus | modulus byte-search (both endiannesses, per the trap table below) + the choke-point capture (below) | Block bytes + search order used | Modulus-length blocks point at RSA-class; the constant search confirms |
| 256 | RSA-2048-class modulus | same as 128-byte row | Block bytes | Modulus scale reads directly from block size |

## Constant-search traps

**Family: constant-hunt failure decode (IDA-class static-read vocabulary)**

Byte-search for a known canonical constant is the default move — these are
the three ways it silently misses:

| Trap | What it looks like | Do this instead | Evidence to capture | Variant inspiration |
|---|---|---|---|---|
| Endianness flip | The word-aligned constant lives in memory in the opposite word order from the canonical table — file-order byte-search misses it | Search BOTH word orders of the constant's words; the emulator's memory dump shows the in-memory order at runtime | Both byte orders tried | Storage order vs compute order are independent choices |
| ARM64 movz/movk split | A 32-bit constant assembled from two immediates (movz low half, movk high half) — the assembled value exists only at runtime, never in the file bytes | Disassembly-search the HALVES as immediates (low 16 and high 16); or read the assembled value off an emulator instruction trace at register width | The two immediates + trace row | The constant is CONSTRUCTED, not stored — search the construction |
| Shared-IV ambiguity | One constant block serves two algorithms (an IV reused across digest and cipher paths) — attributing it to the wrong family | Attribute with a SECOND discriminator: behavioral shape (digest length/truncation per falsifier family 7) or xref from the boundary path (falsifier family 12's parameter-verification shape) | The second witness result | A constant is evidence of availability, not of use — use needs a second witness |

## Key-provenance ladder (five postures)

**Family: key-origin laddering (falsifier family 2(a) trichotomy, recovery-side extension)**

The origin decides the capture channel. Order the postures by observation
cost — cheap channels first:

| Posture | The key is... | Observation channel | Evidence to capture | Variant inspiration |
|---|---|---|---|---|
| 1. rodata literal | hardcoded in the native library's constant section | constant-hunt at the boundary function's data refs; verify by choke-point capture (below) | Data-ref list + capture match | The trichotomy's hardcoded face |
| 2. Managed-layer constant | hardcoded in the Java/dex layer, passed across the boundary per call | JNI argument capture at the boundary method | Argument bytes per call | Same face, one layer up — capture the argument, not the store |
| 3. Server-delivered | a response field reused as key material | response capture + usage trace from delivery point to consumption point | Delivery-to-use trace | The trichotomy's server-delivered face |
| 4. Device/install-derived | derived from device properties or install state | property-API observation on device and in harness (android-fingerprint-apis seeds name the probe surface) | Property reads both sides | The trichotomy's derived face |
| 5. Runtime-derived | derived at runtime from other captured material (agreement, obfuscated derivation) | derivation trace from the last stable input to the key — the choke-point capture names the consumer even when the derivation is opaque | Consumer + input lineage | The capture point does not need the derivation to be readable |

## Choke-point capture (RSA family)

**Family: bignum interposition (libc-symbol interposition vocabulary)**

| Choke point | Why it works | Cost | Evidence to capture | Variant inspiration |
|---|---|---|---|---|
| BN_mod_exp_mont (bignum modular exponentiation, Montgomery representation) | RSA-family private and public operations funnel through modular exponentiation regardless of custom padding/wrapper layers upstream — the hook captures padded plaintext blocks and modulus material at the mathematical floor | One symbol hook; wrapper-layer customization is invisible to it | Argument block dumps at every fire | Interpose below the wrapper layer — the wrapper is variable, the arithmetic floor is not |

```java
// Choke-point hook skeleton (adapt the callback signature to your emulator
// build's hook API — class names follow its public hook face).
Dobby dobby = Dobby.getInstance(emulator);
Symbol bnExp = module.findSymbolByName("BN_mod_exp_mont");
dobby.instrument(bnExp, new InstrumentCallback<Arm64RegisterContext>() {
    @Override
    public void onInstruction(Emulator<?> emulator, long address,
                              Arm64RegisterContext ctx) {
        long r = ctx.getXLong(0), a = ctx.getXLong(1);   // result, plaintext block
        long p = ctx.getXLong(2), m = ctx.getXLong(3);   // exponent, modulus
        System.out.printf("[bnexp] r=0x%x a=0x%x p=0x%x m=0x%x%n", r, a, p, m);
        // dump the pointed bignum blocks: the modulus bytes identify the key
        // posture (provenance ladder above); the plaintext block is the
        // padded input — captured at the mathematical floor, wrappers bypassed.
    }
});
// NOTE: callback class/method names drift across unidbg builds — pin to
// YOUR build's hook API; the symbol-instrumentation face above is stable.
```

## Verification moves

**Family: recovery verification (replay-gate vocabulary)**

| Move | Scenario | How | Expected outcome (hypothesis phrasing) | Evidence to capture | Variant inspiration |
|---|---|---|---|---|---|
| Signature-reuse detection | Before recovering an algorithm at all: is the "signature" computed per request? | Capture two requests with byte-identical bodies moments apart | Identical signatures = the field is reused/cached material — the recovery task dissolves honestly (nothing to recover); differing = computed per-request, proceed | The two captures | Kill the cheapest hypothesis first |
| Emulator-as-verifier | The rewrite keeps failing replay; device round-trips are the slow oracle | Feed identical controlled inputs to the rewrite and the emulated binary; diff INTERMEDIATES (state after each stage), not only outputs | The first diverging intermediate names the wrong assumption — the same localization logic the device-pair diff uses, at iteration speed | Intermediate dumps both sides | The emulator is the cheap oracle; the device pair stays the closure judge (native-sign-recovery step 6) |
| Failure-class triage + stack-reading | A capture/verify run fails and the next move is unclear | Classify the failure class FIRST: exception-thrown vs stall vs silent-wrong-answer — each class owns a different next move (below) | The class, read off the failure surface, routes the iteration; skipping the classification burns harness edits on the wrong class | The failure surface verbatim | Same decode-first discipline as unidbg-env-filling's failure surface |

Failure-class routing: **exception** — the stack names the missing
environment answer (read the whole JNI stack: the top managed frame names
the call, the native return address names the call site); **stall** —
dispatch-integrity first (the parent-call discipline, unidbg-env-filling's
syscall section); **silent wrong answer** — no failure will fire, build the
comparator pair (device reference vs emulator observation) and let the
first differing hop localize the gap.

```python
# Avalanche probe (falsifier family 1 face): a real digest/cipher propagates
# one input-bit flip into ~half the output bits; a per-byte wrapper does not.
def flip_bits(data: bytes):
    for i in range(len(data) * 8):
        yield data[:i // 8] + bytes([data[i // 8] ^ (1 << (i % 8))]) + data[i // 8 + 1:]

def avalanche(fn, sample: bytes, trials: int = 32) -> float:
    flipped = total = 0
    for mutated in list(flip_bits(sample))[:trials]:
        a, b = fn(sample), fn(mutated)
        total += len(a) * 8
        flipped += sum(bin(x ^ y).count("1") for x, y in zip(a, b))
    return flipped / total     # ~0.5 = strong avalanche; ~0.0-0.1 = per-byte transform
```

### Few-shot — the movz/movk constant hunt (synthetic)

```python
# canonical SHA-256 K[0] = 0x428a2f98; file byte-search misses it.
target = 0x428A2F98
lo, hi = target & 0xFFFF, target >> 16          # 0x2f98, 0x428a
# disassembly search: movz x8, #0x2f98 ; movk x8, #0x428a, lsl #16
# (or) read the assembled register mid-trace:
trace_rows = [("0x...c10", "movz x8, #0x2f98"), ("0x...c14", "movk x8, #0x428a,lsl 16")]
assembled = None
for _, ins in trace_rows:
    if "movz" in ins: assembled = int(ins.split("#")[1].rstrip(","), 16)
    if "movk" in ins: assembled |= int(ins.split("#")[1].split(",")[0], 16) << 16
assert assembled == target                       # constant found in its construction
```

## Closure summary

| Gate | Minimum evidence |
|---|---|
| Family oriented | A length prior stated AND a second discriminator applied — priors orient, they never conclude |
| Constant attributed | The constant found in storage (either word order) or in construction (split immediates) + a second witness against shared-IV ambiguity |
| Key posture pinned | The provenance posture named with its observation channel — not assumed |
| Verify move executed | Reuse ruled out, or the emulator-as-verifier diff localized the wrong assumption |

## Cross-references

- The ladder every move here feeds: [native-sign-recovery.md](../signing/native-sign-recovery.md)
- The environment answers the harness consumes while verifying: [unidbg-env-filling.md](unidbg-env-filling.md)
- Family-label falsifiers (digest/HMAC/native-standard): [falsifier-library.md](../../method/process/falsifier-library.md)
- Substrate decisions that got the harness running: [unidbg-harness-bringup.md](unidbg-harness-bringup.md)
- Device-probe surfaces behind key posture 4: [android-fingerprint-apis.md](android-fingerprint-apis.md)
