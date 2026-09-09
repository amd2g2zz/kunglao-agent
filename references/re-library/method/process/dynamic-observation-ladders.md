---
name: dynamic-observation-ladders
description: Channel-descent discipline for instrumented dynamic observation on hardened Android targets — static reading is the first observation channel to go blind, libc import hooks the second, inline-syscall sites the floor, and the JNI function table is the boundary channel; tracing must be windowed to the target module, funnelled macro-to-micro, module loads latched before their code runs (the latch doubles as the load-trace diagnosis for attach kills), and Java-face hooks need the runtime classloader switch before a crypto-class census. Use when hooks fire never or partially, when tracing crashes or stalls the target, when the agent dies at attach, when a memory patch must be proven, when Java/native boundary traffic needs systematic observation, or when runtime observation stays empty and the next channel down must be chosen deliberately.
domain: method
family: process
---

# Dynamic Observation Ladders (channel descent + windowed discipline)

The default observation plan — read the decompilation, hook the imports, trace the process — fails in a fixed order, and each failure names the next channel down. This card is the descent order, the windowing discipline that keeps the target alive long enough to observe, and the closure gates for the patches the observation enables.

## When to Use

- Static reading yields structure but not behavior: the interesting logic sits behind indirect branching and encrypted pools.
- Import hooks fire never or partially — pick the next channel down instead of stacking more hooks on a dead channel.
- Tracing crashes, stalls, or drowns the target in events.
- A patch must be proven, or a module's offsets must be captured before its own code runs.
- Java/native boundary traffic must be observed systematically, not export by export.

## The channel-descent rule (channels go blind in a fixed order)

Default: read the decompiled module, find the interesting call, hook it. This fails because hardened modules branch indirectly (targets resolve only at runtime) and keep sensitive material in encrypted pools — the read gives shape, never values. Next default: hook the libc imports feeding that code. This fails because the module can bypass libc entirely: inline `mov w8, #NR; svc #0` sites invoke the kernel directly, and no import hook fires. "Import hooks see nothing" is not a bug to debug — it is the report that the import channel is blinded and the descent continues.

Floor: **SVC-site observation** — static search for SVC sites in the module, the arm64 syscall table mapping (`w8` = syscall number, `x0`-`x5` = arguments), attach at the sites. Under the syscall floor there is no userspace channel left; if this one is blinded too, the question changes channels (emulation, static extraction), not tools.

## Windowed tracing (whole-process tracing is the failure, not a style)

Default: follow the main thread for the whole run. This fails two ways — performance (flattened targets execute millions of blocks; the capture outgrows any parse) and stability (the volume itself kills the target before the interesting window). Fix: **follow-on-enter / unfollow-on-leave** around the target function, and exclude every other module (libc, linker, framework) from the trace. Window first, trace inside the window — the window is part of the evidence record, not an implementation detail.

## The macro-to-micro funnel

Default: enable full instruction events and grep afterwards. This fails because the interesting facts are not recoverable post hoc — indirect targets exist only at runtime and the volume buries them. Three passes, each narrowing the next:

1. **Call-census pass** (call-summary-class events): under flattening the structure is unreadable but the heat is not — hot offsets surface through the noise; the survivors define the window.
2. **Raw-event parse pass**: parse the raw event stream to resolve indirect targets to concrete offsets (`blr x8` has no static answer); feed the resolved offsets back into the static tool and re-read.
3. **Instruction-filter pass** (transform + callout): keep only the instructions the question needs — operand type `mem` with access `w`/`rw` selects the memory read/write sites, and the callout resolves each effective address at execution time.

## Early-load latch (multi-source convergent = invariant)

Default: attach, then look up the module by name. This fails for late-loaded modules: the lookup races the module's own initialization, and a base seized mid-init yields offsets that work once and never again. Fix: latch the loader — hook the linker's `do_dlopen` + `call_constructor` pair (re-entrancy flag so recursive dlopens do not re-trigger), or the portable `android_dlopen_ext` `onLeave` variant, and **seize the module base before its code runs**. Convergent across three independent sources — treat as an invariant of the observation plan, not a stylistic choice.

**Diagnosis direction (the same latch, run backwards).** Default when the agent keeps dying at attach: blame the agent version or device stability and retry. That fails because hardened targets ship a dedicated anti-instrumentation module whose initialization performs the kill — the retry loop is measuring the kill, not the stability. Run the latch as a tracer instead: record every load with its position in the sequence, and the module loaded immediately before the process dies is the offender. Neutralize it (patch its init to a no-op via the scan-patch loop, or remove it from the package when the app tolerates absence), then re-attach. The load-order record is the evidence — keep it in the ledger next to the kill.

## The scan-patch loop (write without protect is the failure)

Default: scan for the pattern, write the patch. This fails with an access violation — code pages are `r-x`. Fix loop: pattern scan → `Memory.protect` (to `rwx`) **before** the write → retry on the access-violation signature → behavioral verification. Verification is the closure gate and borrows the replay-gate philosophy: the patch is proven when **the target's own verdict flips** under identical inputs — write success proves only that bytes moved. Length constraint: replacement <= original bytes (+ trailing NUL for string-class writes); longer corrupts adjacent memory and manufactures a second bug on top of the first.

## The JNI-boundary channel (one attach covers the whole table)

Default: hook the individual exports the Java layer reaches (`GetStringUtfChars`-class) one attach at a time. This fails two ways: the surface runs ~230 functions deep, so per-export hooking degenerates into whack-a-mole and silently misses the calls nobody thought to name; and each hook site is its own detection surface. Fix: hook the **JNIEnv function table** once — resolve the env pointer, attach to the table slots — and a single attach point observes every call crossing the Java/native boundary. Boundary arguments and returns render from the JNI signatures; local/global reference tracking renders object lifecycles (the reuse trap: after a local reference is deleted the runtime reuses its value, so unexpired references mislabel later arguments — track and expire them).

This is the boundary channel native-sign-recovery's boundary-first ladder hooks into at step 2: the ladder locates the boundary method, this channel observes everything crossing it. Filtering discipline: full-table tracing is enormous noise — class/method scoping at trace time is mandatory, the same window-first philosophy as above. Known blinding: table-integrity checks compare the env-table pointers against the libart-expected addresses and detect table hooks (falsifier-library family 14) — every channel in this card carries a named blinding. Tool note: jnitrace-class tools implement this channel; standing rule — old-tool corpus entries carry a version-compat audit against the current Frida surface before distillation (rows below).

## The Java-face channels (loader switch first, then census)

Default on the Java face: attach and hook the classes you remember — the digest/MAC/cipher/signature getters and their engine methods. That fails two ways. First, business classes often live in a dex loaded at run time, so hooks resolved against the default class factory never fire — the Java twin of the "hook never fires" miss (row below). Fix: latch the loader — hook the loader class (`BaseDexClassLoader`-family), gate on the dex path carrying the target marker, **switch the class factory's loader** to that instance, then install the class hooks. This is the Java counterpart of the native `do_dlopen` latch; the convergent latch discipline now holds across four independent sources. Second, per-class hooking degenerates into the JNI-table lesson repeated: names get missed and each hook site is its own detection surface. Fix: census the whole crypto-class family in one pattern — every overload of the digest/MAC/cipher/signature getters and do-final-class methods — with three capture rules: (1) dual-encode every dump, hex AND base64 (which encoding the consumer sees is unknown a priori; the shape triage downstream needs raw bytes); (2) keep the stack trace with every capture (call-stack membership is the signing-entry falsifier, falsifier-library family 5b); (3) null-check arguments inside the hook and enumerate the overloads — an unguarded hook that assumes a non-null argument crashes the target and manufactures the instability being debugged.

Plaintext-recovery variant: when the request body is assembled into a map/container class, hook the put/insert filtered to the assembling class — the plaintext exists at insertion time even when the wire format is encrypted. Unfiltered, collection-class hooks drown the capture in framework traffic; the class filter is the Java face of window-first.

## Failure-signature → fix

| Failure signature | Diagnosis | Fix |
|---|---|---|
| `writeUtf8String` access violation | page not writable | protect first (scan-patch loop) |
| hook never fires | static tool image-base offset (e.g. a `0x100000` default) not corrected | rebase to `0x0` before computing offsets; offsets are file-relative |
| verdict changes every run | randomized anti-tamper — return spoofing anticipated | stop spoofing returns; falsify the input (falsifier-library family 11) |
| import hooks see nothing | inline syscalls bypass libc | descend to the SVC floor (channel-descent rule) |
| `TypeError: Memory.readUtf8String is not a function` on frida >= 16 | 15.x-era static memory helpers removed in 16.0.0 | NativePointer instance methods (`ptr.readUtf8String()`) — already the norm in modern agents |
| agent runs on 16.x, dies on 17.x at `Module.findExportByName` | static Module APIs removed in 17.0.0 | `Process.getModuleByName(m).getExportByName(n)`; cache the Module object |
| Java-layer hooks fire never | business classes resolve under a runtime-loaded classloader, not the default factory's | loader switch: latch the loader, switch the factory's loader, re-install hooks (Java-face channels) |
| target dies at/just after attach, no hook ran | dedicated anti-instrumentation module initialized | load-trace diagnosis: the module loaded immediately before the kill is the offender; neutralize, re-attach (early-load latch, diagnosis direction) |

## Channel capability boundary

Stalker is solid on arm64; arm32 support is incomplete. Reaching for Stalker on an arm32 target is a channel-capability error, not a script bug — re-route the question to a channel that exists (hook-level observation, emulation) rather than debugging the tool.

## Worked examples (synthetic)

Values invented; shapes transferable. Every listing models the worker contract: observations land in `evidence/*.json` as structured records — a script that prints and exits has produced nothing a checker can read.

### Example 1 — windowed transform-Stalker with memory-access filter

```js
// frida >= 16, arm64. Values synthetic. Ledger persists to
// evidence/observe-window.json via the host runner — never print-and-lose.
const MOD = "libvault.so";                    // synthetic module name
const LEDGER = [];
const emit = (rec) => LEDGER.push(rec);
// pass 1: call census — flattening noise hides structure, not heat
const hot = callCensus(MOD);                  // call-summary-class pass
const tid = hot[0].tid;                       // the window is the census' thread
for (const m of everyModuleExcept(MOD)) Stalker.exclude(m);
Stalker.follow(tid, {                         // follow on-enter, unfollow on-leave
  transform(next) {
    for (let i = next.next(); i !== null; i = next.next()) {
      const memOp = i.operands.some(o => o.type === "mem" && /w|rw/.test(o.access));
      if (memOp) next.putCallout((c) => emit({   // EA resolves only at runtime
        channel: "stalker-mem", module: MOD,
        pc: i.address.sub(moduleBase(MOD)).toInt32(),
        ea: effectiveAddr(i, c) }));           // structured record
      next.keep();
    }
  }
});
```

### Example 2 — early-load latch, then scan → protect → patch

```js
// All values synthetic. Latch BEFORE the module's code runs or every later
// offset is a race. APIs on the current Frida surface (16/17-clean — no
// legacy Memory.write* statics, no static Module lookups).
let base = null;
const once = { armed: true };                 // re-entrancy flag
Interceptor.attach(Module.getGlobalExportByName("android_dlopen_ext"), {
  onLeave() {
    if (!once.armed) return;
    const m = Process.findModuleByName("libvault.so");
    if (m == null) return;
    once.armed = false; base = m.base;        // base seized pre-init
    const hit = Memory.scanSync(m.base, m.size, "d5 3f 07 9f 21 07 00 91");
    Memory.protect(hit[0].address, 8, "rwx"); // BEFORE the write — r-x pages
    hit[0].address.writeByteArray(            // instance method, not the
      [0x1f, 0x20, 0x03, 0xd5, 0x1f, 0x20, 0x03, 0xd5]); // removed static
    // replacement length <= scanned length (+1 NUL for string writes);
    // longer corrupts adjacent memory.
  }
});
// closure = behavioral: re-run the target's own check under identical
// inputs; its verdict flips = patch proven (write success proves nothing).
```

### Example 3 — SVC-site observation with input falsification

```js
// The floor under blinded import hooks. Prework (static): search `svc #0`
// sites with the image base corrected to 0x0, map w8 (nr) + x0-x5 (args)
// per the arm64 syscall table.
const SVC_OFFSETS = [0x4a1c, 0x8f30];         // precomputed sites (synthetic)
const NEEDLE = "/data/local/tmp/probe.bin";   // synthetic path of interest
const decoy = Memory.allocUtf8String("/data/local/tmp/absent.bin");
for (const off of SVC_OFFSETS) Interceptor.attach(base.add(off), function () {
  const nr = this.context.x8.toInt32();       // w8 = syscall number
  if (nr !== 56 /* openat */ && nr !== 63 /* read */) return;
  const arg = this.context.x1.readUtf8String();
  emit({ channel: "svc", site: off, nr: nr, path: arg });  // evidence record
  if (arg === NEEDLE) this.context.x1 = decoy; // falsify the INPUT the check
});                                           // reads — not the verdict it returns
// verdicts randomized across identical runs = anti-tamper tell: return
// spoofing is anticipated; input falsification is not (falsifier family 11).
```

## Closure summary

| Gate | Minimum evidence |
|---|---|
| Channel chosen | The blinding that killed the previous channel is named (static / imports / SVC ladder position) |
| Window bounded | Follow/unfollow pair + exclude list recorded with the trace |
| Load latched | Module base seized before its first instruction — latch record in the evidence file |
| Boundary observed | JNI-table hook + trace-time class/method filter recorded; reference-expiry accounted |
| Java hooks live | Loader switched to the target's instance before class-hook install; crypto census captures carry hex+base64 dumps and stack traces |
| Patch proven | Target's own verdict flips under identical inputs — behavioral, not write-success |
| Findings persisted | Structured records in `evidence/*.json` — printed output is not evidence |

## Cross-references

- Tool quick-reference behind every channel: [tools-dynamic.md](../../tools/dynamic/tools-dynamic.md)
- When observation itself is detected and blocked: [anti-analysis.md](../../anti-analysis/catalog/anti-analysis.md)
- The protection whose detection shell kills the agent (build-side view of the diagnosis direction): [vm-protection-anatomy.md](../../patterns/vm/vm-protection-anatomy.md)
- Verdict-stability, constant-pool, and channel-integrity falsifier rows: [falsifier-library.md](falsifier-library.md)
- The boundary-first ladder this card's JNI channel hooks into: [native-sign-recovery.md](../../android/signing/native-sign-recovery.md)
