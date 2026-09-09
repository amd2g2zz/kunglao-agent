---
name: vm-protection-anatomy
description: Anatomy of VM-class native-library protection kept as one build-side/peel-side map — what the protector constructs (method bodies hollowed into a custom interpreter VM, encrypted instruction stream loaded at runtime, controlled symbol exports with runtime JNI registration, damaged branch targets, detection shell around the loader) is exactly where the analyst peels (handler-table recovery, loader-first key recovery, RegisterNatives as the address map, branch repair to READ, shell peel before VM peel), plus the versioned-SO adaptation loop and the dispatch-bridge marginal. Use when a hardened native function decompiles into a dispatch loop with semantic-free case bodies, when the .so exposes no usable business symbols, when the decompiler CFG reads as corrupted by construction, when an encrypted code stream must be peeled, or when the same protected SO family must be re-analyzed after a version bump.
domain: patterns
family: vm
---

# VM Protection Anatomy (build side ↔ peel side)

Protection builders and analysts describe the same object from opposite
ends. This card holds both in one map: every build-side feature is also the
analyst's entry point, because the feature exists to be consumed by the
runtime — and anything the runtime consumes can be observed or read.
Evidence base: the build-side rows are practitioner-attested from two
independent defender-perspective write-ups (custom interpreter construction;
stream encryption + dynamic loading); the peel-side rows converge from an
analyst-side multi-version series on one hardened commercial SO family plus
one worked emulator instance (third-party-repost provenance — technique
claims inherit the caveat; version-specific constants and offsets are case
facts and are never carried here).

## When to Use

- The interesting function decompiles into a dispatch loop whose case
  bodies are semantic-free, and no plain algorithm is reachable from it.
- The .so exposes no `Java_...`/business symbols; the name search is empty
  before analysis starts.
- The decompiler CFG is wrong by construction: branch targets into padding,
  register-indirect jumps whose tables will not decode.
- A protected method's real logic lives in an encrypted stream the loader
  decrypts at run time.
- The same protected SO family must be re-analyzed at the next version and
  the question is what transfers vs what died.

## The build side (what the protector constructs)

| Build feature | What it looks like on disk / at run time |
|---|---|
| Hollowed methods + interpreter VM | Protected method bodies are replaced by a stub call into a bundled interpreter (stream id / pointer + length as arguments); the real logic is a custom instruction stream executed by a loop + dispatch table |
| Encrypted instruction stream | The stream is stored ciphertext (AES-class); the loader derives the key and decrypts at load — the disassembler shows the interpreter, never the protected logic |
| Controlled symbol exports | Export table stripped to the minimum (often only `JNI_OnLoad`); native handlers reach the Java layer via runtime registration, decoupling Java names from native symbols |
| Branch-target damage | Jump tables / branch operands encoded or corrupted so CFG reconstruction fails — deliberate, not bit-rot: the runtime resolves real targets through its own repair path |
| Detection shell | Anti-debug / anti-hook inventory wrapped around the loader and the VM entry (falsifier-library families 11, 15-17), so observation dies before the peel starts |

## The 1:1 map (each build feature is a peel entry)

| Build feature | Why the default peel fails | First move |
|---|---|---|
| Interpreter VM | You would devirtualize with flattening-class tooling; that fails because the case bodies are semantic-free dispatch targets, not inlined expressions — the variant label comes first (vm-deobfuscation-routing Part B "VM-ized") | Handler-table recovery: trace the loop → opcode→handler map → replay the stream (jsvmp-triage methodology, native face) |
| Encrypted stream | You would analyze the method from the disassembly; that fails because the logic is ciphertext data, not instructions | Peel the loader first: the stream key is derived IN the loader — recover the derivation, decrypt, dump, then analyze the dump as bytecode |
| No exports | You would treat the library as unrecoverable and hunt strings; that fails because runtime registration IS a map — the registration array pairs every Java native declaration with a function pointer | Read or hook the registration call inside `JNI_OnLoad`; the array dump is the Java↔native address table (few-shot 1) |
| Branch damage | You would trust the decompiler CFG or give up when it loops; that fails because damage is by construction — the CFG is wrong before analysis begins | Repair to READ (section below): resolve real targets, patch into a working COPY, never trust the pre-repair graph |
| Detection shell | You would start at the VM; that fails because the shell kills the observation channels the peel needs | Peel the shell first — integrity families (11) then instrumentation-detection families (15-17); in emulators the fake-content discipline applies (family 17) |

## Devirtualization methodology (analyst side)

Default: read the interpreter's handlers one by one until the algorithm
emerges. That fails on scale — each handler is reached hundreds of times
with different operands, and per-execution reading never assembles the
stream. The working order:

1. **Map**: trace the dispatch loop; record (opcode value → handler address)
   pairs until new opcodes stop appearing. Density check: a covered map
   explains every dispatch observed in a replay window.
2. **Lift**: for each handler exactly once, write its semantics (inputs,
   outputs, next-stream-position rule). Handlers are small; the lift is
   mechanical once the operand convention is read.
3. **Replay**: decode the captured stream with the map + lifts and re-emit
   linear code for the protected method.
4. **Verify**: differential replay — lifted re-implementation vs the VM (or
   the emulator) over captured inputs; divergence localizes a wrong lift or
   a mis-decoded operand.

Decision rule: devirtualize when the goal is to KNOW the algorithm;
emulate when the goal is to RUN it (native-sign-recovery's two gates).
A stream that decodes cleanly but lifts into unmaintainable size is an
emulation answer, not a lift failure.

## Branch/jump repair (repair to READ, not to run)

Default: patch the binary so the decompiler stops complaining. That fails
because the repair must be derived, not invented — a guessed target
manufactures a false CFG that reads plausibly and poisons everything
downstream. Working discipline:

- Resolve real targets from the resolution path itself: the table-lookup
  code that the runtime executes IS the decoder — read it (or trace it once)
  and apply the same computation statically.
- Repair into a COPY; keep the original hash in the evidence file. The
  repaired copy is a reading aid, not a drop-in runtime artifact.
- Verify the repair before reading: every resolved target lands in valid
  code, the CFG terminates, and a short runtime trace's observed edges are a
  subset of the repaired graph. A repaired edge the runtime never takes is
  suspect; an observed edge the graph lacks means the repair is incomplete.

## The versioned-SO adaptation loop

Default at a version bump: re-run the whole analysis from zero, or worse,
carry last version's offsets forward. Both fail: from-zero discards the
family knowledge that made the last version tractable; carried offsets are
dead on arrival because versioned re-hardening reshuffles the layout. The
transferable heuristic is the loop, not the facts:

1. **Diff the protection set**: what did this version add or change (new
   shell checks, stream cipher change, export policy) vs the recorded
   inventory of the previous version.
2. **Re-locate stable anchors by function, not address**: the registration
   routine, the dispatch loop, the loader — they persist across versions as
   roles even as every address dies.
3. **Re-derive per-version material fresh**: offsets, tables, keys, command
   ids. Record them version-stamped; a fact that survives one bump is a
   finding, a rule that survives every bump is the heuristic.

## Dispatch bridges (marginal)

Command-id → handler and string → handler bridges are the SO-family
protocol's function table: one entry point takes a command id (or a
command-name string), a table routes it. Once located, the bridge is the
fastest inventory of what the library can do — enumerate the table before
reading any handler. The ids/names are case facts (version-stamped, never
distilled); the bridge SHAPE — entry, bounds check, table dispatch, result
marshal — is the transferable pattern.

## Few-shots (synthetic)

Values invented; shapes transferable. Every listing models the worker
contract: structured records land in `evidence/*.json`, never print-and-lose.

### Example 1 — no-exports recovery via the registration array

```js
// The .so has no Java_ symbols. The registration call inside JNI_OnLoad
// pairs each declared native with a function pointer — read it, and the
// export table is reconstructed without a single symbol.
const regLedger = [];  // structured ledger -> evidence/jni-registration.json
const regNatives = Process.getModuleByName("libart.so")   // 16/17-clean lookup
  .getExportByName("_ZN3art3JNI15RegisterNativesEP7_JNIEnvP7_jclassPK15JNINativeMethodi");
Interceptor.attach(regNatives, (a) => {
  const env = a[0], clazz = a[1], methods = a[2], count = a[3].toInt32();
  for (let i = 0; i < count; i++) {
    // JNINativeMethod = { const char* name; const char* sig; void* fnPtr; }
    const rec = { idx: i, name: methods.add(i * 24).readPointer().readCString(),
                  sig:  methods.add(i * 24 + 8).readPointer().readCString(),
                  fn:   methods.add(i * 24 + 16).readPointer() };
    regLedger.push(rec);         // name may be NULL when names are stripped —
  }                              // sig+fn still pair with the Java declaration
  emit({clazz: classFrom(clazz, env), methods: regLedger});
});
```

### Example 2 — encrypted stream peel (loader first, stream second)

```python
# Order matters: the stream key exists only inside the loader's run.
# 1) trace the loader once; find the derivation inputs (recorded):
loader_trace = {"const_seed": "9c1f...", "runtime_salt": "derived@load",
                "cipher": "AES-CTR-class", "stream_vaddr": 0x2a100}
# 2) re-derive the key offline from the recorded derivation, decrypt:
key = derive(**loader_trace)                    # same derivation, no device
stream = decrypt(blob_at(loader_trace["stream_vaddr"]), key)
# 3) verify the dump BEFORE analyzing: sizes consistent, opcode values fall
#    inside the mapped range, replay of a captured window executes cleanly.
assert stream_parses(stream, opcode_map)         # mapped opcodes only
emit_evidence("evidence/stream-dump.json", meta=loader_trace, sha256=sha(stream))
```

## Closure summary

| Gate | Minimum evidence |
|---|---|
| Variant labeled | VM-ized label survives its falsifier (vm-deobfuscation-routing Part B) before any countermeasure work |
| Shell peeled | Instrumentation/integrity families named and neutralized; observation channel proven alive on the target |
| Stream peeled | Key derivation recorded from the loader; dump parses under the recovered opcode map |
| Map recovered | Registration array (or equivalent) recorded — every Java native paired with a function pointer |
| Repair verified | Resolved targets land in valid code; runtime-traced edges are a subset of the repaired graph |
| Replay closed | Lifted (or emulated) output passes the gate named for its goal — byte-exact or consumer-acceptance |

## Cross-references

- Variant label comes first (VM-ized vs flattening-class):
  [vm-deobfuscation-routing.md](vm-deobfuscation-routing.md)
- Trace → opcode map → replay methodology outline: [jsvmp-triage.md](../../web/vm/jsvmp-triage.md)
- Runtime JNI registration mechanics: [languages-platforms.md](languages-platforms.md#android-jni-registernatives-obfuscation-htb-wondersms)
- Emulation half (stubbing loop, the two closure gates): [native-sign-recovery.md](../../android/signing/native-sign-recovery.md)
- Observation channels the shell attacks (latch, windowing, JNI table):
  [dynamic-observation-ladders.md](../../method/process/dynamic-observation-ladders.md)
- Shell inventory as falsifier families (integrity, trap, metadata probe, fake-content): [falsifier-library.md](../../method/process/falsifier-library.md)
