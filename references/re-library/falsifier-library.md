---
name: falsifier-library
description: Hypothesis-family to falsification-experiment library — for the recurring reverse-engineering hypothesis families (digest family, HMAC structure, block-cipher mode, protobuf body, signing entry point, absent network capability, native-standard algorithm, fact conflict, async entry point, obfuscation variant) this card lists the kill experiments — the trigger to run and what the positive and the negative outcome each prove. Use when registering a candidate in the hypothesis layer (every candidate must enter with a named falsifier), when an open hypothesis has stalled without an executed experiment, or when choosing the one experiment that discriminates two competing candidates.
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
| **11. Environment verdict is framework-forged** (integrity layer; practitioner-attested, single-source-exempt) | (a) Randomized-verdict tell: the identical input replayed across runs yields different verdict codes → the target anticipates return spoofing — move the intervention to the INPUT the check reads (input falsification at the observation layer; exemplar: dynamic-observation-ladders.md example 3); ✗ stable verdict = ordinary conditional, peel normally. (b) Observable-marker bisimulation: attr-prev file containing the zygote context string <=> Zygisk-class framework active; mount-table dump containing framework marker mounts <=> root framework present → ✓ the integrity layer is externalized — neutralize at the framework layer before peeling in-process checks; ✗ absence proves nothing (markers are forgeable; checks may be in-process). (c) The peel-loop (family method): checks are a stack — neutralize the top check's input, re-run, the next surfaces; termination = the top-level verdict stabilizes across identical runs (layered-defense logic: [stacked-protections.md](stacked-protections.md) orthogonality). |
| **12. Algorithm family by constant pool** (complements family 7's output-shape channel; multi-source) | (a) rodata cross-reference: known cipher tables / encodings byte-searched in the constant pool → ✓ family-level identification before any code reading; ✗ absent = table-less or recomputed constants — absence is not non-standard. (b) Parameter verification: recovered parameters (tables, IVs, key schedule) replayed through an independent implementation against captured pairs → ✓ implementation-level closure, behavior-confirmed; ✗ parameters wrong or consumed differently — re-extract from the binary. Constant presence alone stays family-level support, never closure — mirror of family 7's shape-labels-hypothesis rule. |
| **13. Crash signature → vulnerability-hypothesis class** (thin family; evidence side only) | (a) Allocator-misuse signatures (double-free / dangling-reuse patterns in the crash allocation trace) → hypothesis class: reuse-after-free — falsify by lifetime audit of the owning allocation; ✗ trace clean → move to the arithmetic side. (b) Arithmetic-overflow signatures (allocation size derived from a controllable length, undersized buffer) → hypothesis class: integer wrap — falsify by recomputing the size expression at its extremes. (c) Boundary-adjacent access signatures (crash within a few bytes of an allocation edge) → hypothesis class: off-by-one / adjacency overwrite — falsify by bounding the index expression. (d) Mitigation state as provability fact: name each present mitigation and what it does to the hypothesis — MTE-class tagging makes memory-safety hypotheses directly provable/refutable; NX + ASLR-class makes control-flow hypotheses demand an info-leak first. Scope: concept teaching excluded (model prior covers it); exploitation walkthroughs excluded (the agent does not exploit). |
| **14. JNI-boundary observation is detected** (channel-integrity mirror) | Experiment: env function-table pointers verified against the libart-expected addresses → ✓ table hook present — the boundary channel is blinded (falsifier-library's mirror of "import hooks see nothing"); re-route below the table layer or change channels; ✗ pointers intact — table hooks absent, but absence proves only this channel (other tells may fire). Companion to families 6 and 11: every observation channel carries a named blinding — name it when choosing the channel (dynamic-observation-ladders.md, channel-descent rule). |
| **15. Instrumentation is detected via a trap channel** (practitioner-attested; complements family 11's file/marker channels) | (a) Self-trap probe: the target raises a SIGTRAP-class trap with its own handler installed; under an attached debugger the OS routes the signal to the debugger and the handler never runs → ✓ handler skipped / branch not taken = the trap channel is identified — pass signals through to the target (nostop+pass-class debugger configuration) or move the question to a channel without a ptrace-class debugger (emulation, static); ✗ handler runs = that channel is absent on this target. (b) Multi-detection inventory: detection checks arrive in stacks (TracerPid read, maps scan, port probe, thread-name scan, trap channel, ...); neutralizing one surfaces the next — run family 11(c)'s peel-loop channel-for-channel; termination = the target's verdict stabilizes across identical runs. (c) Kernel-floor note: a detection implemented below the userspace instrumentation layer has NO agent-side counter — routing the question to emulation or another channel is the fix; debugging the tool is not. |
| **16. Hook detection via runtime-metadata pointer probes** (worked-instance attested) | The probe shape: the target holds a handle it treats as a raw metadata pointer (MethodID-class) and reads a flag offset from it — instrumentation frames alter the expected flag word, so the read IS the detector. Falsifier: in emulators the probed address is unmapped and the read faults → ✓ SIGSEGV at a metadata-offset read = the probe is identified (this is a detection-channel signature, NOT a stubbing bug — do not stub it away); ✗ read succeeds and flags look instrumented = the probe fired and must be answered (counter below). Counter class — probe-memory allocation: map garbage memory at the probed address so the probe read succeeds; partial-fidelity reads are tolerated when the goal is to run (consumer-acceptance gate, native-sign-recovery degradation path). |
| **17. Anti-debug fake files must be plausible, not merely present** (emulator-context worked instance) | Faking `/proc/self/status` with `TracerPid: 0` is necessary and insufficient: status/stat/wchan-class consumers grep specific lines and fields (an R-state process line, a sleeping-syscall wchan value). Falsifier: run the target's own check in-emulator with a file-IO trace open → ✓ the check's verdict stabilizes = the fake-content set is complete; ✗ verdict still fires = a consumed field is still implausible — diff the fake against a real reference dump FIELD-BY-FIELD instead of adding more fake files (selectively editing real dump content survives field greps that wholly invented content fails). |
| **18. Debugger attach refused / JDWP thread absent** (setup-side enablement family; complements the detection-side families 11/15 — refusal happens before any instrumentation could be the cause) | (a) Decision-order probe: Android grants debuggability via `ro.debuggable=1` (boot image) or the app manifest's `android:debuggable=true`; when attach is refused, read `adb shell getprop ro.debuggable` FIRST → ✓ 0 = the target depends on the per-app manifest flag and this family owns the failure; ✗ 1 = debuggability is granted image-wide, so a refusal here is NOT a debuggability failure — skip to (c)'s alternate-signature branch. (b) Enablement ladder, preference order: flip `ro.debuggable=1` via the image/mprop route (survives across apps) before the per-APK manifest repackage + resign rung (per-target toil); AVD emulators default `ro.debuggable=1`, so on an emulator this family tends to be closed already — expect a post-flip getprop re-read to show the change. Classic JDWP-thread viewers (DDMS) are removed from the modern SDK — the observation channel is the attach itself. (c) Re-verify closure (the fix's own falsifier): re-read getprop + attach retry with the debugger of record (jdb-class JDWP attach on the Java face; native debug agents on the so face — `android_server` is legacy 32-bit naming, modern IDA ships `android_server64`) → ✓ attach succeeds / the JDWP thread appears = the debuggability hypothesis is confirmed and the signature closed; ✗ still refused = the fix did not own this failure — suspect a different signature (ptrace-tracee slot exhaustion or an anti-debug family: families 11/15) and re-triage rather than deepen the enablement ladder. |

### Few-shot — length-extension feasibility, family 2 (synthetic)

```python
# captured: 32-hex signature over unknown key || payload (MD5 shape).
# H(secret || payload) with a native Merkle-Damgard hash is extendable
# WITHOUT knowing the secret:
orig   = b"sid=7f3a&ts=1717000000"            # captured payload
suffix = b"&admin=1"                          # payload we want signed too
forged_sig = length_extension(                # glue padding + carry state
    digest=captured_sig,
    secret_len=SECRET_LEN_GUESSES,            # brute the block padding offset
    suffix=suffix)
# replay the forged pair (orig || suffix, forged_sig):
#   accepted  -> secret-prefix structure + native MD5, BOTH confirmed
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

### Few-shot — probe-memory allocation, family 16 (synthetic)

```python
# The SO treats a MethodID-class handle as a raw metadata pointer and reads
# a flag offset from it — the read is the HOOK DETECTOR. In the emulator the
# address is unmapped: the SIGSEGV is the probe's signature, not a stub bug.
PROBE_ADDR = 0xAAAAB000                          # faulting address (synthetic)
emulator.map(PROBE_ADDR, 0x1000, perms="r--")    # garbage tolerated: the probe
# only inspects the flag word — partial-fidelity reads pass when the goal is
# to run. Re-run the boundary pair: the fault is gone and the command
# sequence advances. Do NOT "fix" this by stubbing the faulting read — the
# stub answers THIS probe only and the next probe reads a different offset.
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
- Layered-defense orthogonality behind the family 11 peel-loop:
  [stacked-protections.md](stacked-protections.md)
- Observation-channel discipline (SVC floor, JNI-boundary channel, windowing)
  the families 11/14 interventions run inside:
  [dynamic-observation-ladders.md](dynamic-observation-ladders.md)
- The protection these detection families guard (loader, stream, VM entry):
  [vm-protection-anatomy.md](vm-protection-anatomy.md)
- Stubbing-loop context for the family 16 counter (probe-memory allocation)
  and the family 17 fake-content discipline:
  [native-sign-recovery.md](native-sign-recovery.md#the-incremental-stubbing-loop-emulation-half)
- Which evidence type may update what after a falsifier fires:
  [verification-safety.md](verification-safety.md#evidence-type-vocabulary)
