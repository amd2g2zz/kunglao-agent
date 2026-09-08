---
name: unidbg-env-filling
description: Strategy inputs and failure-signature field guide for unidbg-class Android native emulation — a capability-bounded vocabulary of observation and patching moves (emulator instruction/module trace, its own JNI-table visibility, device-side windowed path and boundary traces, IDA-class static read, patching as a path-changing move), two worked scenarios showing how to compose them, and the failure-signature catalog that decodes the WARN log, tells syscalls from JNI trampolines, and dispatches each gap class to its override point (unknown syscall / partial syscall / final-or-switch-locked handler / JNI signature switch / IOResolver file chain / libc-symbol interposition), with supply-class triage before stubbing, the vDSO trap for time-family hooks, and init-window deltas (lazy class resolution, record/replay fallback). Use when an emulation harness crashes, throws UnsupportedOperationException, stalls on an SVC, returns values a real device would not, or runs clean but answers wrong. Not for on-device dynamic analysis (tools-dynamic), not for the boundary-first algorithm-recovery ladder itself (native-sign-recovery owns the stubbing loop and the replay gate that closes it — this card widens what the agent can compose with, it does not prescribe), not for the substrate decisions that precede filling (unidbg-harness-bringup), and not for device-farm emulation detection on live targets.
domain: android
family: emulation
---

# unidbg env-filling (failure-signature field guide)

Emulating an Android native library outside a device means supplying every
piece of environment the library touches: JNI callbacks into the Java
layer, syscalls, file reads, libc symbols. The incremental stubbing
discipline, per-stub validation, and closure gates live in
[native-sign-recovery.md](native-sign-recovery.md); this card supplies the
strategy inputs and failure signatures that discipline consumes.

## Deployment preconditions (before any harness runs)

unidbg-class emulators are host-side Java tooling, and the environment
fails before any target code runs if this is not in place:

- **JDK (Java) + Maven** toolchain must be deployed first — the emulator
  is a Maven-structured Java project (`pom.xml`, Maven wrapper included);
  an IDE with the JDK configured is the usual working surface.
- **The emulator and its dependency tree are pulled from remote**: clone
  the source repository, then let the **first build resolve the Maven
  dependencies** over the network. Expect the first build to be the slow
  one; offline hosts stall here, not at emulation time.
- The Android-facing module ships a pull script for the bundled Android
  system libraries and prebuilt backend binaries; run it if system-library
  resolution fails at load time.
- **Backend choice is a trade, not a default**: the fast JIT-class backend
  buys speed and costs some instrumentation capability; the default
  backend keeps the richer hook surface. Choose per goal — run-fast vs
  analyze-deep — and re-choose if trace hooks go quiet after a switch.
- Log verbosity is a log4j-class config lever: raising the file/syscall
  logger from INFO to DEBUG turns silent environment misses into visible
  access traces — do this before debugging any gap below.

## Reading the failure surface

**Family: observation-channel decoding (dynamic-observation-ladders vocabulary)**

Every gap below announces itself in the harness log first. Decode before
patching:

| Failure signature | Do this first | Evidence | Variant inspiration |
|---|---|---|---|
| `WARN ... handleInterrupt intno=2, NR=<n>, svcNumber=0x0, syscall=null` | Treat as an unhandled **syscall**: look up `<n>` in the per-arch syscall table; `PC` points inside libc, `LR` names the target-library call site | 1 article; SVC-floor concept independently attested cross-cluster (3 articles total) | Same decode serves any emulator: interrupt-class log + register snapshot -> gap identity |
| Same line but `svcNumber != 0x0`, or `UnsupportedOperationException` naming a `Class->method` signature | It is a **JNI trampoline**, not a syscall — route to the JNI section below; the exception text IS the missing signature | 3/4 tetralogy articles | JNI-boundary observation channel (dynamic-observation-ladders) prints the same signature shape |
| Harness stalls mid-run with no further log | A hand-written dispatch replaced the parent handler but skipped the PC-advancing supercall — restore it | 1 article | Any layered hook: forgetting to call through freezes the whole lane |

## Strategy inputs: observation and patching moves

Environment filling is a means, never the goal — these are moves to
compose per situation, not steps in a procedure. Each entry states what
it costs and what it can and cannot prove; the choice is the agent's.

**Family: capability-bounded move vocabulary (observation-channel + interposition vocabulary)**

| Move | Precondition | Cost | Proves / blinds |
|---|---|---|---|
| Emulator instruction trace (one call; unscoped or module-range; granularities: function / basic-block / instruction — instruction is the primitive the others build from) | Harness runs the target function | Medium: high line rates on paper, roughly a quarter of that with range filtering; hours on hardened samples | Proves the exact executed path with per-instruction register context; blind to the device side — it shows only what the CURRENT environment lets run |
| Module-scoped window + load-time latch (listener-callback enable, so init-array/JNI_OnLoad code is inside the window; stop/start per window) | Module load observable | Small | Proves early-load behavior without system-library noise; blinds everything outside the window |
| Emulator-side JNI-table visibility (the emulator implements the table; verbose logging prints every boundary call) | Verbose enabled | Negligible | Proves which Java-layer calls the library makes and what the harness answers; blind to whether those answers match a device — that needs a comparator |
| Device-side windowed path trace (Stalker-class; window + latch discipline per dynamic-observation-ladders) | On-device instrumentation channel | High: setup and fragility; ARM32 support partial | Proves the ground-truth path a device takes for a given input — the comparator half for every emulator answer |
| Device-side boundary trace (jnitrace-class) paired with manual app operation | Device + Frida-class injection | Medium | Proves which JNI calls fire in natural execution and their real returns; blinds nothing about emulation — it is the reference, not the subject |
| IDA-class static/debugging read | Binary loads in the tool | Medium | Proves the static path inventory: input-dependent branches (byte compares, length checks, checksums) and which branch a given input must take; blinds values that exist only at runtime |
| Patching aimed at the path (a branch or return patch CHANGES what executes next — it can steer execution into deeper code for capture, beyond neutralizing a check) | A located decision point | Small edit, but every later observation is taken on YOUR path, not the target's natural one | Proves reachability of deeper code; blinds natural-path behavior — captures taken on a patched path say nothing about the unpatched one until replay-validated |
| MCP debug session (breakpoint mode: pause the run via the debug entry point, start the MCP server from the paused console; interactive register/memory/disassembly/stepping/trace tools) | The harness reaches a breakpoint — execution completing without hitting one ENDS the process and the session with it | Interactive session cost; not fully autonomous — the harness skeleton around the breakpoint is still yours to build | Proves live mid-run state inspection; blinds nothing after the run ends — the session has no post-mortem life |
| MCP custom tools (toolkit mode: register custom tools over a loaded native library; the AI re-runs the target with different parameters while process and server stay alive) | A registered toolkit in the harness | One-time registration; persists across invocations | Proves parameter-sweep interaction without re-attaching per run — the natural companion to multi-sample capture discipline |

Move-vocabulary evidence note: the trace/JNI/patching rows are
corpus-evidenced (tetralogy attestation per the catalog tables below);
the two MCP rows are owner-verified against the tool's official README
(the corpus attests MCP-assisted analysis in-cluster via an IDA-side
server — 1 article — not the emulator's own MCP surface).

## Worked scenarios (reasoning shape; synthetic values)

**Scenario — clean run, wrong answer.** The harness completes; output
differs from the captured device sample. The catalog above is mute (no
crash). Compose instead: device-side boundary trace of one manual
operation gives the JNI calls the library really makes and their real
returns; the emulator-side table shows the same calls and what the
harness answered. The first differing return localizes the gap — fill
exactly that behavior, re-run, and let the replay gate decide closure
(all captured pairs byte-exact, per native-sign-recovery step 6). What
this scenario teaches: when no failure signature fires, a comparator PAIR
(device reference vs emulator observation) localizes what a crash trace
would have named.

**Scenario — the trace that ends too early.** The emulator trace stops
at an input check (static read shows a length compare the captured inputs
never satisfy). Two composable options, judged per case: construct inputs
from the captured pair set that reach past the check — impossible if the
branch guards a mode natural use never enters; or patch the branch to
take the deeper path under trace and capture the algorithm body there.
The second option's captures are evidence about the deeper code, NOT
about natural execution — reproduction built from them validates only
against unpatched-path captured pairs, through the same replay gate.
What this scenario teaches: patching is a path-changing move; aim it
deliberately and price its blindness into the closure claim.

## The gap catalog (prior knowledge: failure signatures informing strategy choice)

**Family: incremental stubbing loop (native-sign-recovery vocabulary) — one crash, one stub, re-validate each stub against captured pairs**

### JNI gaps (Java-layer calls the library makes)

| Failure signature | Do this first | Evidence | Variant inspiration |
|---|---|---|---|
| `UnsupportedOperationException` with a full method signature | Turn on VM verbose logging, add a `switch` on the signature inside the JNI-provider override, return a plausible DVM object; **fall through to super for unhandled cases** so the next crash still names a real gap | 3/4 tetralogy articles | Per-signature dispatch is the JNI twin of syscall dispatch — same loop, different table |
| Static field / enum constant read | Return a DVM object whose value is the constant's string — later `name()`-class calls then resolve correctly | 1 article | Environment constants as data, not code: one string answers a whole check family |
| Collections crossing the boundary | Wrap a real host-language map/list object as a proxy DVM object; implement accessor calls against the real object | 2/4 | Any rich object crossing a boundary can be proxied instead of reimplemented |
| Struct-like objects or raw pointer returns | Either intercept the field-access calls, or `malloc` emulator memory, fill fields at offsets, and return the address as a long | 1 article | Struct-fill at explicit offsets is the same skill as syscall-struct fill (rows below) |

### Init-window deltas (queue aggregation)

**Family: init alignment (stubbing-loop vocabulary; queue cluster: unidbg harness operations)**

| Failure signature / trap | Do this first | Evidence | Variant inspiration |
|---|---|---|---|
| **Class-hierarchy pre-resolution trap** — init behaves differently after you force-resolve the target's class hierarchy ahead of it ("pre-loading to save time") | Do not pre-resolve: eager class-hierarchy resolution makes init observe a population it never sees on device and can divert its registration/check path. Resolve lazily — what the trace demands, when it demands it | 1 queue source | Lazy-vs-eager supply: eager supply is itself an environment change (same lesson as maps — serve what the caller looks for) |
| Init cannot be made to run at all (hardened, self-checking, or emulator-incompatible init) | Record init's device-side effects once (registered natives, set fields, created objects) and replay them into the harness as canned answers — then let the boundary-pair replay gate decide whether the canned init suffices | 1 queue source | Capture the answer instead of re-fighting the gate — the record/replay posture |

### Syscall gaps

**Supply-class triage (queue aggregation):** classify the gap into one of
three supply classes BEFORE writing the stub — (1) value-answer (compute
from register inputs, no world state), (2) struct-fill (write through
caller pointers per the man page), (3) dispatch-integrity (handle it AND
preserve the parent dispatch — poison the NR, call the parent so PC
advances). The class decides which override point applies; a class-(3) gap
answered as class-(1) passes one probe and freezes the next run.

| Failure signature | Do this first | Evidence | Variant inspiration |
|---|---|---|---|
| NR unimplemented (`handleUnknownSyscall` path) | Override the unknown-syscall hook; `switch` on NR; write outputs through the argument pointers; return success. Struct outputs: fill a byte buffer in **little-endian**, field order per the man page | 1 article (2 worked cases) | Man-page-driven struct fill generalizes to every metadata syscall |
| NR implemented but wrong/incomplete for the target | Override the specific named handler method if it is virtual | 1 article | Partial-behavior override beats full replacement — keep the working halves |
| Handler method is `final` / buried in a switch | Override the **top-level dispatch** instead: read the syscall-number register, handle your NR, write results, then poison the number register with an invalid value so the parent re-dispatch cannot overwrite — and always call the parent so PC advances | 1 article (2 cases) | "Intercept at the earliest unowned layer" — same move as pre-load interposition on device |
| Callers expect environment variation (CPU id changes per call, affinity mask reflects N cores) | Return values a real kernel would vary: randomize within a plausible core count, set low bitmask bits for N cores, never all-zero | 1 article | Emulation-vs-device tell: constant answers where hardware varies is a fingerprint — vary deliberately |
| Time-family syscall throws on non-wall clocks | Map clock classes: wall-clock ids to host time, monotonic ids to a monotonic host source, CPU-time ids to a small monotonically growing value (never zero); unknown ids degrade to wall time instead of raising | 1 article | Degrade-don't-throw keeps the run alive long enough to reach the next real gap |
| Time-family hook installed at NR level never fires, yet clock values flow | The platform routed the call through the **vDSO** userspace fast path — no SVC, no NR dispatch, so an NR-level hook is structurally blind. Intercept at the libc symbol level instead (clock-class symbol hook), or disable vDSO exposure in the emulator's memory layout | 1 queue source (explicit trap) | A skipped virtualization layer blinds hooks at THAT layer — drop one layer down; do not arm harder at the same one |

### File-access gaps

**Family: environment-integrity bypass (anti-analysis / falsifier-library family 17 vocabulary — plausible content, hypothesis-grade)**

| Failure signature | Do this first | Evidence | Variant inspiration |
|---|---|---|---|
| Library reads a file the emulator has no answer for | Register a custom file resolver **before loading the library** (late registration silently never fires); resolve returns one of: success(FileIO), explicit errno, or pass-to-next | 2/4 articles (chain order attested in both) | Chain-of-responsibility file virtualization — same shape as mount-namespace tricks on device |
| `/proc/self/cmdline` | Serve generated bytes; use the `self` symlink form (pid churn-proof) and keep the trailing NUL the format requires | 2 articles | Format-plausibility beats content-plausibility: a missing NUL breaks parsers downstream |
| `/proc/self/status` (TracerPid probe) | Serve a full template with TracerPid 0 and ids matching the emulator's own pid — fuller templates survive stricter parsers | 2 articles | Answer the check the file carries, not the file name |
| `/proc/self/maps` | Three strategies, pick by intent: default emulator map (clean, hides instrumentation, but lacks APK mapping); real device map (fullest, **but any address dereference against it crashes** — switch away at the first bad-address fault); minimal on-demand construction — serve exactly the entries the caller's logic looks for | 2 articles | "It reads maps to find X" -> serve X; serving a whole world invites dereference crashes |
| `/proc/net/*` | **Do not fill.** Modern Android denies these to apps anyway, and copied content imports proxy/tool ports INTO the environment — a self-inflicted detection | 1 article (explicit rationale) | Sometimes the truest answer is the access failure itself |
| su/tool paths | Do not fabricate. Let the access fail (ENOENT) — the realistic no-root answer | 1 article | Faking presence is the amateur tell; absence is the target state |
| APK path read (signature/resource checks) | Map the target's APK path to the real file via the plain-file IO object — path varies per device, read the actual access from the log | 2 articles | Feeds signature-check reads; countermeasures on the device side in [signature-check-bypass.md](signature-check-bypass.md) |

### libc-symbol gaps

**Family: symbol-surface interposition (tools-dynamic hook vocabulary)**

| Failure signature | Do this first | Evidence | Variant inspiration |
|---|---|---|---|
| Value probe inconsistent with a real device (`gettid` vs `getpid` main-thread equality; property reads empty) | Inline-hook the libc symbol (symbol name varies across bionic versions — try both), force the return value; for property reads use the emulator's property-provider hook, unhandled keys fall through to defaults | 2 articles | One hook at the symbol answers every caller — cheaper than N call-site patches |
| Writability/anti-syscall probe via `open()` | Hook the symbol and return -1 for the probe path only; pass everything else through | 1 article; device-side twin cross-cluster (2 total) | Selective failure: deny the probe, keep the world running |
| System-call-chain functions (`popen`-class: vfork/pipe/exec/wait chains) | **Do not chase the chain.** Hook the entry function to capture its intent (the command string), let it run, and fake only the two decisive syscalls it triggers (pipe fd pair as two 4-byte writes; fork returning an incrementing positive pid) | 1 article | High-level intent capture + low-level result forgery composes; neither half alone suffices |
| Property interrogation (`__system_property_get` fingerprint census) | Provider hook or symbol hook; write value + NUL, return length; non-matching keys pass through to the original | 1 article | Device-side fingerprint seeds for the same APIs: android-fingerprint-apis |

## Emulation-vs-device divergence tells

| Observable | Likely divergence | Evidence | Variant inspiration |
|---|---|---|---|
| All-zero file metadata from a directory fd | Emulator's default directory stat stub is the zero struct — fill non-zero mode/size/inode/timestamps | 2 articles | Zeroed answers are their own fingerprint; audit every default stub's answer once |
| TID != PID on the "main" thread | Single-thread emulator model breaks main-thread assumptions — force TID=PID | 1 article | Thread-model divergences generalize: any per-thread identity probe needs a deliberate answer |
| CPU-time clock yields 0 or throws | Unmapped clock id — small monotonic non-zero value | 1 article | Anti-zero discipline: checks often test `> 0`, not truthiness |

## Cross-references

- The loop this catalog serves (order heuristic, per-stub validation, closure gates): [native-sign-recovery.md](native-sign-recovery.md)
- Device-side detection channels these fakes answer: [anti-analysis.md](anti-analysis.md), [detection-engineer.md](detection-engineer.md)
- Trace/observation channels while filling: [dynamic-observation-ladders.md](dynamic-observation-ladders.md)
