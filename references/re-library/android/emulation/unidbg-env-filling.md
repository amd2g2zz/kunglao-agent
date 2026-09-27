---
name: unidbg-env-filling
description: Strategy inputs and failure-signature field guide for unidbg-class Android native emulation — a capability-bounded vocabulary of observation and patching moves (emulator instruction/module trace, its own JNI-table visibility, device-side windowed path and boundary traces, IDA-class static read, patching as a path-changing move), two worked scenarios showing how to compose them, and the failure-signature catalog that decodes the WARN log, tells syscalls from JNI trampolines, and dispatches each gap class to its override point (unknown syscall / partial syscall / final-or-switch-locked handler / JNI signature switch / IOResolver file chain / libc-symbol interposition), with supply-class triage before stubbing, the vDSO trap for time-family hooks, and init-window deltas (lazy class resolution, record/replay fallback). Use when an emulation harness crashes, throws UnsupportedOperationException, stalls on an SVC, returns values a real device would not, or runs clean but answers wrong. Not for on-device dynamic analysis (tools-dynamic), not for the boundary-first algorithm-recovery ladder itself (native-sign-recovery owns the stubbing loop and the replay gate that closes it — this card widens what the agent can compose with, it does not prescribe), not for the substrate decisions that precede filling (unidbg-harness-bringup), and not for device-farm emulation detection on live targets.
domain: android
family: emulation
---

# unidbg env-filling (failure-signature field guide)

Emulating an Android native library outside a device means supplying every piece of environment the library touches: JNI callbacks into the Java layer, syscalls, file reads, libc symbols. The incremental stubbing discipline, per-stub validation, and closure gates live in [native-sign-recovery.md](../signing/native-sign-recovery.md); this card supplies the strategy inputs and failure signatures that discipline consumes.

## Deployment preconditions (before any harness runs)

- **JDK (Java) + Maven** toolchain must be deployed first — the emulator
  is a Maven-structured Java project (`pom.xml`, Maven wrapper included).
- **The emulator and its dependency tree are pulled from remote**: clone
  the source repository, then let the **first build resolve the Maven
  dependencies** over the network; offline hosts stall here. The
  Android-facing module ships a pull script for bundled system libraries.
- **Backend choice is a trade, not a default**: the fast JIT-class backend
  buys speed and costs some instrumentation capability; the default
  backend keeps the richer hook surface. Re-choose if trace hooks go quiet.
- Log verbosity is a log4j-class config lever: raising the file/syscall
  logger from INFO to DEBUG turns silent environment misses into visible
  access traces — do this before debugging any gap below.
- A working harness skeleton lives at `templates/unidbg/harness.java.tmpl`
  (`scripts/install_unidbg.sh` installs the toolchain); the skeletons below
  slot into it.

## Reading the failure surface

Every gap below announces itself in the harness log first. Decode before
patching:

| Failure signature | Do this first | Evidence to capture | Variant inspiration |
|---|---|---|---|
| `WARN ... handleInterrupt intno=2, NR=<n>, svcNumber=0x0, syscall=null` | Treat as an unhandled **syscall**: look up `<n>` in the per-arch syscall table; `PC` points inside libc, `LR` names the target-library call site | Log line + PC/LR register snapshot | Same decode serves any emulator: interrupt-class log + registers -> gap identity |
| Same line but `svcNumber != 0x0`, or `UnsupportedOperationException` naming a `Class->method` signature | It is a **JNI trampoline**, not a syscall — route to the JNI section below; the exception text IS the missing signature | The exception text verbatim | JNI-boundary observation channel (dynamic-observation-ladders) prints the same signature shape |
| Harness stalls mid-run with no further log | A hand-written dispatch replaced the parent handler but skipped the PC-advancing supercall — restore it | Last log line + thread state | Any layered hook: forgetting to call through freezes the whole lane |

## Strategy inputs: observation and patching moves

Environment filling is a means, never the goal — moves to compose per situation, not steps in a procedure. Each entry states what it costs and what it can and cannot prove; the choice is the agent's.

| Move | Precondition | Cost | Proves / blinds |
|---|---|---|---|
| Emulator instruction trace (one call; unscoped or module-range; function / basic-block / instruction granularity — instruction is the primitive) | Harness runs the target function | Medium: high line rates, roughly a quarter after range filtering; hours on hardened samples | Proves the exact executed path with per-instruction register context; blind to the device side — shows only what the CURRENT environment lets run |
| Module-scoped window + load-time latch (listener-callback enable, so init-array/JNI_OnLoad is inside the window) | Module load observable | Small | Proves early-load behavior without system-library noise; blinds everything outside the window |
| Emulator-side JNI-table visibility (verbose logging prints every boundary call) | Verbose enabled | Negligible | Proves which Java-layer calls the library makes and what the harness answers; blind to whether answers match a device — that needs a comparator |
| Device-side windowed path trace (Stalker-class; window + latch discipline per dynamic-observation-ladders) | On-device instrumentation channel | High: setup and fragility; ARM32 partial | Proves the ground-truth device path for a given input — the comparator half for every emulator answer |
| Device-side boundary trace (jnitrace-class) paired with manual app operation | Device + Frida-class injection | Medium | Proves which JNI calls fire naturally and their real returns; it is the reference, not the subject |
| IDA-class static/debugging read | Binary loads in the tool | Medium | Proves the static path inventory: input-dependent branches and which branch an input must take; blinds runtime-only values |
| Patching aimed at the path (a branch/return patch CHANGES what executes next — it can steer into deeper code for capture) | A located decision point | Small edit, but later observations are on YOUR path | Proves reachability of deeper code; blinds natural-path behavior until replay-validated |
| MCP debug session (breakpoint mode: pause via the debug entry point, interactive register/memory/stepping tools) | The harness reaches a breakpoint — completing without one ENDS the session | Interactive session cost | Proves live mid-run state inspection; no post-mortem life |
| MCP custom tools (toolkit mode over a loaded library; re-run with different parameters, process stays alive) | A registered toolkit | One-time registration; persists | Proves parameter-sweep interaction without re-attaching per run |

## Worked scenarios (reasoning shape; synthetic values)

**Clean run, wrong answer.** No crash signature fires. Compose: device-side boundary trace of one manual operation (real JNI calls + real returns) vs the emulator-side table (same calls + what the harness answered). The first differing return localizes the gap — fill exactly that behavior, re-run, and let the replay gate decide closure.

**The trace that ends too early.** Static read shows a length compare the captured inputs never satisfy. Either construct inputs that reach past the check (impossible if the branch guards an unreachable mode), or patch the branch to take the deeper path under trace. Patched-path captures prove things about the deeper code, NOT natural execution — validate only against unpatched-path captured pairs, through the same replay gate.

## The gap catalog

**Family: incremental stubbing loop (native-sign-recovery vocabulary) — one crash, one stub, re-validate each stub against captured pairs**

### JNI gaps (Java-layer calls the library makes)

| Failure signature | Do this first | Evidence to capture | Variant inspiration |
|---|---|---|---|
| `UnsupportedOperationException` with a full method signature | Turn on VM verbose logging, add a `switch` on the signature inside the JNI-provider override, return a plausible DVM object; **fall through to super for unhandled cases** so the next crash still names a real gap | Signature + returned object shape | Per-signature dispatch is the JNI twin of syscall dispatch — same loop, different table |
| Static field / enum constant read | Return a DVM object whose value is the constant's string — later `name()`-class calls then resolve correctly | The constant's usage site | Environment constants as data, not code: one string answers a whole check family |
| Collections crossing the boundary | Wrap a real host-language map/list as a proxy DVM object; implement accessor calls against the real object | Accessor call list | Any rich object crossing a boundary can be proxied instead of reimplemented |
| Struct-like objects or raw pointer returns | Intercept the field-access calls, or `malloc` emulator memory, fill fields at offsets, and return the address as a long | Field offsets touched | Struct-fill at explicit offsets is the same skill as syscall-struct fill |

### Init-window deltas

**Family: init alignment (stubbing-loop vocabulary)**

| Failure signature / trap | Do this first | Evidence to capture | Variant inspiration |
|---|---|---|---|
| **Class-hierarchy pre-resolution trap** — init behaves differently after you force-resolve the target's class hierarchy ahead of it ("pre-loading to save time") | Do not pre-resolve: eager resolution makes init observe a population it never sees on device. Resolve lazily — what the trace demands, when it demands it | Init behavior diff pre/post force-resolve | Lazy-vs-eager supply: eager supply is itself an environment change |
| Init cannot be made to run at all (hardened, self-checking, emulator-incompatible) | Record init's device-side effects once (registered natives, set fields, created objects) and replay them into the harness as canned answers — then let the boundary-pair replay gate decide | The recorded init effect list | Capture the answer instead of re-fighting the gate — the record/replay posture |

### Syscall gaps

**Supply-class triage:** classify the gap into one of three supply classes
BEFORE writing the stub — (1) value-answer (compute from register inputs,
no world state), (2) struct-fill (write through caller pointers per the man
page), (3) dispatch-integrity (handle it AND preserve the parent dispatch —
poison the NR, call the parent so PC advances). The class decides which
override point applies; a class-(3) gap answered as class-(1) passes one
probe and freezes the next run.

| Failure signature | Do this first | Evidence to capture | Variant inspiration |
|---|---|---|---|
| NR unimplemented (unknown-syscall path) | Override the unknown-syscall hook; `switch` on NR; write outputs through the argument pointers; return success. Struct outputs: fill a byte buffer in **little-endian**, field order per the man page | NR number + struct layout filled | Man-page-driven struct fill generalizes to every metadata syscall |
| NR implemented but wrong/incomplete for the target | Override the specific named handler method if it is virtual | Behavior diff vs device pair | Partial-behavior override beats full replacement — keep the working halves |
| Handler method is `final` / buried in a switch | Override the **top-level dispatch** instead: read the syscall-number register, handle your NR, write results, then poison the number register with an invalid value so the parent re-dispatch cannot overwrite — and always call the parent so PC advances | Register dump at dispatch | "Intercept at the earliest unowned layer" — same move as pre-load interposition on device |
| Callers expect environment variation (CPU id per call, affinity mask for N cores) | Return values a real kernel would vary: randomize within a plausible core count, set low bitmask bits, never all-zero | Repeated-call answer diff | Constant answers where hardware varies is a fingerprint — vary deliberately |
| Time-family syscall throws on non-wall clocks | Map clock classes: wall-clock ids to host time, monotonic ids to a monotonic host source, CPU-time ids to a small monotonically growing value (never zero); unknown ids degrade to wall time instead of raising | The throwing clock id | Degrade-don't-throw keeps the run alive long enough to reach the next real gap |
| Time-family NR hook never fires, yet clock values flow | The platform routed the call through the **vDSO** userspace fast path — no SVC, no NR dispatch, so an NR-level hook is structurally blind. Intercept at the libc symbol level instead, or disable vDSO exposure in the emulator's memory layout | Trace showing clock reads with no SVC | A skipped virtualization layer blinds hooks at THAT layer — drop one layer down; do not arm harder at the same one |

### File-access gaps

**Family: environment-integrity bypass (falsifier-library family 17 vocabulary — plausible content, hypothesis-grade)**

| Failure signature | Do this first | Evidence to capture | Variant inspiration |
|---|---|---|---|
| Library reads a file the emulator has no answer for | Register a custom file resolver **before loading the library** (late registration silently never fires); resolve returns one of: success(FileIO), explicit errno, or pass-to-next | The access path + flags from the log | Chain-of-responsibility file virtualization — same shape as mount-namespace tricks on device |
| `/proc/self/cmdline` | Serve generated bytes; use the `self` symlink form (pid churn-proof) and keep the trailing NUL the format requires | Parsed result downstream | Format-plausibility beats content-plausibility: a missing NUL breaks parsers |
| `/proc/self/status` (TracerPid probe) | Serve a full template with TracerPid 0 and ids matching the emulator's own pid — fuller templates survive stricter parsers | The probe's read offset pattern | Answer the check the file carries, not the file name |
| `/proc/self/maps` | Three strategies, pick by intent: default emulator map (clean, hides instrumentation, lacks APK mapping); real device map (fullest, **but any address dereference against it crashes** — switch away at the first bad-address fault); minimal on-demand construction — serve exactly the entries the caller looks for | Fault address on first bad deref | "It reads maps to find X" -> serve X; serving a whole world invites dereference crashes |
| `/proc/net/*` | **Do not fill.** Modern Android denies these to apps anyway, and copied content imports proxy/tool ports INTO the environment — a self-inflicted detection | The denial result | Sometimes the truest answer is the access failure itself |
| su/tool paths | Do not fabricate. Let the access fail (ENOENT) — the realistic no-root answer | The ENOENT | Faking presence is the amateur tell; absence is the target state |
| APK path read (signature/resource checks) | Map the target's APK path to the real file via the plain-file IO object — path varies per device, read the actual access from the log | The accessed path string | Feeds signature-check reads; countermeasures on the device side in [signature-check-bypass.md](../signing/signature-check-bypass.md) |

### libc-symbol gaps

**Family: symbol-surface interposition (tools-dynamic hook vocabulary)**

| Failure signature | Do this first | Evidence to capture | Variant inspiration |
|---|---|---|---|
| Value probe inconsistent with a real device (`gettid` vs `getpid` main-thread equality; property reads empty) | Inline-hook the libc symbol (name varies across bionic versions — try both), force the return value; for property reads use the emulator's property-provider hook, unhandled keys fall through to defaults | Symbol + forced value | One hook at the symbol answers every caller — cheaper than N call-site patches |
| Writability/anti-syscall probe via `open()` | Hook the symbol and return -1 for the probe path only; pass everything else through | The probe path string | Selective failure: deny the probe, keep the world running |
| System-call-chain functions (`popen`-class: vfork/pipe/exec/wait chains) | **Do not chase the chain.** Hook the entry function to capture its intent (the command string), let it run, and fake only the two decisive syscalls it triggers (pipe fd pair as two 4-byte writes; fork returning an incrementing positive pid) | Captured command string | High-level intent capture + low-level result forgery composes; neither half alone suffices |
| Property interrogation (`__system_property_get` fingerprint census) | Provider hook or symbol hook; write value + NUL, return length; non-matching keys pass through to the original | Key list probed | Device-side fingerprint seeds for the same APIs: android-fingerprint-apis |

## Emulation-vs-device divergence tells

| Observable | Likely divergence | Evidence to capture | Variant inspiration |
|---|---|---|---|
| All-zero file metadata from a directory fd | Emulator's default directory stat stub is the zero struct — fill non-zero mode/size/inode/timestamps | stat struct dump | Zeroed answers are their own fingerprint; audit every default stub's answer once |
| TID != PID on the "main" thread | Single-thread emulator model breaks main-thread assumptions — force TID=PID | gettid/getpid pair | Any per-thread identity probe needs a deliberate answer |
| CPU-time clock yields 0 or throws | Unmapped clock id — small monotonic non-zero value | The clock id | Anti-zero discipline: checks often test `> 0`, not truthiness |

## Gap-fill skeletons (adapt per target; harness face in templates/unidbg)

```java
// JNI gap: per-signature dispatch inside the JNI-provider override.
// Fall through to super for unhandled cases — the next crash names the
// next gap. (Constant-as-data: one string answers one check family.)
private static class TargetJni extends AbstractJni {
    @Override
    public DvmObject<?> getStaticObjectField(BaseVM vm, DvmClass dvmClass, String signature) {
        if ("android/os/Build->MANUFACTURER".equals(signature)) {
            return new StringObject(vm, "OnePlus");     // plausible, device-consistent
        }
        return super.getStaticObjectField(vm, dvmClass, signature);
    }
}
// vm.setJni(new TargetJni()); vm.setVerbose(true);  — verbose prints every
// boundary call; the first unimplemented signature is the next stub to write.
```

```java
// File gap: IOResolver registered BEFORE loadLibrary (late registration
// silently never fires). /proc templates below are starting points —
// fuller templates survive stricter parsers; keep the trailing NUL.
private static class TargetFileResolver implements IOResolver<NewFileIO> {
    @Override
    public FileResult<NewFileIO> resolve(Emulator<NewFileIO> emulator, String pathname, int oflags) {
        if (("/proc/self/status").equals(pathname)) {           // TracerPid probe
            return FileResult.success(new ByteArrayFileIO(oflags, pathname,
                ("Name:\ttarget\nState:\tS (sleeping)\nTgid:\t" + emulator.getPid()
                 + "\nPid:\t" + emulator.getPid() + "\nPPid:\t1\n"
                 + "TracerPid:\t0\nUid:\t10123\t10123\t10123\t10123\n"
                 + "Gid:\t10123\t10123\t10123\t10123\n").getBytes()));
        }
        if (("/proc/self/cmdline").equals(pathname)) {          // keep the NUL
            return FileResult.success(new ByteArrayFileIO(oflags, pathname,
                "com.target.app\0".getBytes()));
        }
        return null;                                            // pass to next resolver
    }
}
// Syscall gaps: classify supply class first (value-answer / struct-fill /
// dispatch-integrity), then override at the class's own point — the
// unknown-NR callback for class 1+2, the top-level dispatch (poison the NR
// register, still call the parent so PC advances) for class 3. Read the
// unknown-NR branch of your emulator build's syscall handler for the exact
// override surface — it is version-stable in shape, not in name.
```

## Cross-references

- The loop this catalog serves (order heuristic, per-stub validation, closure gates): [native-sign-recovery.md](../signing/native-sign-recovery.md)
- Device-side detection channels these fakes answer: [anti-analysis.md](../../anti-analysis/catalog/anti-analysis.md), [detection-engineer.md](../../malware/reporting/detection-engineer.md)
- Trace/observation channels while filling: [dynamic-observation-ladders.md](../../method/process/dynamic-observation-ladders.md)
