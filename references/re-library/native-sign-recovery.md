---
name: native-sign-recovery
description: Boundary-first recovery of Android native request-signing algorithms — locate the Java-to-JNI boundary, capture plaintext/ciphertext sample pairs, identify the algorithm family by output shape with per-family falsifiers, extract and reproduce offline, and close with a byte-exact replay gate. Pairs with the incremental emulator stubbing loop for running the boundary under unidbg/unicorn-class emulation. Use when a captured request carries a computed signature/token field whose generation crosses into native code.
---

# Native Sign Recovery (boundary-first ladder + stubbing loop)

Reproducing request-signing fields computed inside Android native code.
Two coupled halves — **A** the boundary-first ladder (six ordered steps to
byte-equal offline reproduction), **B** the incremental stubbing loop (the
emulation discipline). Shared closure gate (step 6): unverified replay =
hypothesis, not result.

## When to Use

- A captured request carries a digest/signature-shaped field the Java layer
  merely forwards into a `native` declaration near request construction
  (`System.loadLibrary` + `native` methods feeding the outgoing request),
  and the goal is offline generation.
- The emulation harness keeps crashing: jump to the stubbing loop — but do
  not skip step 2; every stub validates against those captured samples.

## The boundary-first ladder

### Step 1 — Locate the boundary statically

Search the decompiled Java layer (jadx) around request construction:

- HTTP-stack seams: `Interceptor` implementations, header-adding helpers
  (`addHeader`), request builders.
- Naming seams: `sign` / `encrypt` / `token` / `digest` identifiers. Under
  R8/ProGuard obfuscation these read as noise — do name recovery first;
  identifiers come back only after mapping.
- Crypto API seams: `MessageDigest`, `Mac`, `Cipher`, `Base64` usages whose
  output feeds the outgoing request.
- Loading seams: `System.loadLibrary` / `System.load` and the `native`
  declarations they serve.

Deliverable: the boundary method — class name, method name, JNI signature.
Everything later hooks or re-implements exactly this signature. If the
matching `Java_...` symbol is missing from the `.so`, the library registers
handlers dynamically — resolve via `JNI_OnLoad` / `RegisterNatives` first
(see [languages-platforms.md](languages-platforms.md#android-jni-registernatives-obfuscation-htb-wondersms))
before assuming the boundary is unrecoverable.

### Step 2 — Confirm parameters dynamically (multi-sample, never single)

Capture several real requests. Several, not one: a single capture cannot
distinguish static inputs from dynamic ones (timestamps, nonces, counters,
per-install seeds), and step 6 needs the variety.

Hook the boundary method on-device (Frida-class instrumentation) and dump
per invocation: the full argument vector in, the raw return value out.
This yields plaintext→ciphertext pairs — the ground truth every later step
is validated against.

### Step 3 — Identify the family by output shape (hypothesis only)

Classify each dumped output by length and character set:

| Shape | Hypothesis | Falsifier (any one kill kills the label) |
|---|---|---|
| 32 hex | MD5 family | decode = 16 bytes; reference MD5 (prefix/suffix-salt, HMAC variants) over plausible serializations matches; 1-byte input flip ≈ half the output bits flip; canonical constant block present in the boundary function |
| 40 hex | SHA-1 family | decode = 20 bytes; documented IV/round constants present; reference match + avalanche as above |
| 64 hex | SHA-256 family | decode = 32 bytes; documented constants present; reference match |
| N-byte block ciphertext | AES (16) / DES (8) | length ≡ 0 mod block size; canonical S-box present; fixed-key single-block plaintext edit changes only its ciphertext block (ECB probe) — whole-ciphertext diffusion → chaining/stream/custom |
| base64 alphabet | Base64 ± variant | standard decode succeeds; padding arithmetic fits input length — decode fails AND padding breaks → variant table or not base64 |

> **Modified-implementation warning.** The shape names a hypothesis, never
> an implementation. Deployed targets are known to mutate standard
> algorithms — altered IVs, swapped table entries, truncated or
> double-applied digests, custom alphabets. Run the captured pairs through
> the reference implementation BEFORE trusting any family label. A
> shape-matching label that fails the reference match is the common case,
> not the exception: it means extract the real constants from the binary
> (step 4), not force the reference.

### Step 4 — Extract the actual algorithm

Decompile the boundary function and read the algorithm as implemented, not
as labeled. Where the function is flattened (control-flow-flattening-class
obfuscation), recover the real state machine from the dispatcher instead of
reading blocks in file order — handling per
[anti-analysis.md](anti-analysis.md). Constants found here (IVs, tables,
key material, embedded salts) are the ground truth that step 3's shape
hypothesis was only approximating.

### Step 5 — Reproduce offline

1. **Emulate** (preferred): unicorn/unidbg-class harness — exact code paths,
   no rewrite risk; pay the stubbing-loop cost below.
2. **Rewrite**: Python from the step-4 reading — fast to iterate; every
   rewrite decision stays a hypothesis until step 6.

Validate against the step-2 pairs continuously while building.

### Step 6 — Replay gate (closure)

Done only when output is byte-identical to every captured sample — replay
the captured dynamic values (timestamp, nonce), not fresh ones. Mismatch =
a wrong upstream assumption (serialization, parameter order, key
derivation, dynamic-item handling): feed controlled inputs through hook and
reproduction side by side, diff intermediates, fix the assumption — never
the test vector.

## The incremental stubbing loop (emulation half)

Discipline: every crash, missing symbol, and unimplemented JNI callback is
one loop iteration — never a cue to write the whole environment in one
patch.

- **The crash trace decides what to stub next.** Stub exactly what the
  trace names; leave everything else unimplemented so the next crash still
  points at something real.
- **Validate each stub immediately.** After adding one stub, re-run a
  step-2 pair through the boundary. Pass → keep it and move to the next
  crash. Fail → the stub changed behavior it should not have; fix or revert
  before stacking another stub on top.
- **Order heuristic** (empirical): 1. `JNI_OnLoad` (hosts integrity checks
  and dynamic registration later calls depend on) → 2. invoke the target
  boundary directly → 3. JNI callbacks per crash → 4. syscalls/files/
  properties per crash.
- **Dynamic items.** Multi-sample cross-compare (step 2) classifies which
  inputs vary (timestamp/nonce/counter) vs stable (keys, salts, device
  constants); only varying ones need fixed-value injection, and the
  reproduction must accept them as parameters to pass step 6.
- **Degradation path.** Emulator-side deadlocks, thread dependence, or
  timing-sensitive logic that will not stabilize → fall back to pure
  on-device hooking (Frida-class) and extract results from the live
  process. Emulation is a convenience; the replay gate is the requirement.

## Worked micro-examples (synthetic)

Four code-listing decision points; values invented, shapes transferable.

### Example 1 — falsify the SHA-1 label

```python
import hashlib
pt = b"appKey=K1&ts=1717000000&uid=U9"   # captured plaintext
out = "a94f3c..."                        # captured output, 40 hex

# falsifier ladder (step 3):
len(bytes.fromhex(out))                       # 20 -> shape fits SHA-1
hashlib.sha1(pt).hexdigest() == out           # False
hashlib.sha1(pt + b"\n").hexdigest() == out   # False   (newline variant)
# and the SHA-1 IV (67452301 EFCDAB89...) absent from the .so's constants
# -> verdict: custom digest in SHA-1 clothing. Extract the real constant
#    block from the binary (step 4); never force the reference.
```

### Example 2 — block-independence probe kills the CBC label

```python
# 48-byte ciphertext -> AES-family shape. Fixed key, flip ONE byte of
# plaintext block 1, recapture:
ct1 = b"\x00"*48
ct2 = b"\x01" + b"\x00"*47        # only byte 0 of plaintext differs
diff_blocks(ct1, ct2) == [0]      # only ciphertext block 0 changed
# per-block independence -> ECB (CBC diffuses into block 2).
# AES S-box present in the .so -> AES-ECB confirmed as the mode hypothesis.
```

### Example 3 — stubbing-loop: stop on mismatch, do not stack stubs

```python
# run(pair) under emulation, after 2 stubs:
run(capture[0]) == capture[0].out   # False — output differs for same input!
# RULE: do not stub a third thing. The 2nd stub (Build.FINGERPRINT canary)
# changed behavior. Fix it from the captured set, not from imagination:
stub_fingerprint(get_capture_value("Build.FINGERPRINT"))  # re-run -> pass
```

### Example 4 — dynamic-item granularity from multi-sampling

```python
sig(ts="1717000000") == sig(ts="1717000030")   # same minute -> EQUAL
sig(ts="1717000060") != sig(ts="1717000000")   # next minute  -> differs
# the digest consumes minute-truncated time, NOT epoch-ms. Injecting
# epoch-ms would break replay on captured values; inject what the target
# actually consumes.
```

## Closure summary

| Gate | Minimum evidence |
|---|---|
| Boundary located | Hook fires on the declared JNI signature under realistic traffic |
| Family labeled | Reference-implementation match on captured pairs (output shape alone is not evidence) |
| Extraction complete | Constants and control flow read from the binary; emulator or rewrite runs on captured inputs |
| Closed | Byte-identical replay across the full captured sample set |

## Cross-references

- Dynamic JNI registration: [languages-platforms.md](languages-platforms.md#android-jni-registernatives-obfuscation-htb-wondersms)
- Tooling: [tools.md](tools.md#unicorn-emulation), [tools-dynamic.md](tools-dynamic.md#frida-dynamic-instrumentation)
- Flattening countermeasures: [anti-analysis.md](anti-analysis.md)
- Framework-level hiding: [languages-platforms.md](languages-platforms.md#framework-first-routing-android)
