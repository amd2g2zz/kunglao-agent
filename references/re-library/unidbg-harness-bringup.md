---
name: unidbg-harness-bringup
description: Substrate-decision field guide for unidbg-class Android native emulation — the decisions that precede environment filling (choosing an interception slot from the six-candidate shelf, when each may install relative to module load and init, the failure signatures that decode a substrate mischoice — a PLT-class hook that fires once then goes quiet, an instruction hook the fast backend ignores, a harness hang on a dispatched thread — and how an artifact that cannot run unpacked gets loaded anyway via dump-then-load). Use when a harness plan must pick a hook framework, early-only or silent hooks, an instruction hook throws or is ignored on the JIT-class backend, or a packed SO refuses to load or crashes the loader. Not for the environment answers themselves (unidbg-env-filling owns JNI/syscall/file/libc gap filling), not for the recovery ladder and its closure gate (native-sign-recovery), not for device-side detection doctrine (anti-analysis).
domain: android
family: emulation
---

# unidbg harness bring-up (substrate decisions before env filling)

unidbg-env-filling answers what the library READS once it runs. This card
owns the substrate decisions that decide what gets to run at all: which
interception slot to place where, when it may install, and how the artifact
itself enters the emulator when the on-disk form cannot. Split rationale:
the aggregation target (unidbg-env-filling) was at budget, and these are
DECISIONS BEFORE filling, not answers during it — a substrate mischoice
invalidates every later fill, so it is read first.

## When to Use

- A harness plan must choose a hook framework/slot for a specific gap and
  the candidates do not interchange.
- Hooks installed before load fire for the first calls and then go silent,
  or never fire at all.
- An instruction-level hook is ignored or faults on the fast backend.
- The target SO is packed/self-decrypting and refuses to load under
  emulation, or loads and dies inside its unpacking stub.
- The harness hangs mid-run right after a thread-dispatch call.

## The six-candidate selection shelf

**Family: interception-substrate selection (tools-dynamic hook vocabulary;
queue cluster: unidbg harness operations)**

Candidates do not interchange — the gap class picks the slot, not
preference:

| Candidate | When to choose it | Cost | Evidence | Variant inspiration |
|---|---|---|---|---|
| Java-layer bridge override (the emulator's JNI-provider switch) | The gap is a Java-side call the library makes — dispatch on the method signature inside the provider override | Small per signature; every unhandled case must fall through to super so the next gap still names itself | 2 queue sources | Per-signature dispatch owned by unidbg-env-filling's JNI section — this row is the CHOICE, that card owns the fill |
| PLT/GOT-class import redirect (xHook-class) | The gap is an import the library calls through its import table — catch every call site at once without touching code | Small; registration binds to the import snapshot at install time (failure signature below) | 2 queue sources | Import-table interposition — one registration answers every caller |
| Inline-hook engine (Dobby-class prologue patch) | The gap is a symbol whose callers bypass the import table (internal calls, direct branches) or a probe hook must survive import re-resolution | Medium: per-symbol patch + trampoline; survives import-table refresh by construction | 2 queue sources | Symbol-level interposition below the import layer |
| Emulator-native instruction hooks (CodeHook-class callbacks) | The gap needs per-instruction visibility (trace, register snapshot, branch steering) | High line rates; changes with backend (row below) | 1 queue source | The emulator's own instruction channel — the same channel the trace move in unidbg-env-filling consumes |
| Backend-level single-step / memory hooks | Register/memory-conditional observation (watchpoints, per-access traps) | Medium-high | 1 queue source | Watchpoint channel from tools-dynamic vocabulary |
| Device-side Frida-class channel (outside the harness) | The question is what a REAL device does — the comparator/reference half, never the subject under emulation | Device + injection channel | 2 queue sources | Comparator-pair discipline per native-sign-recovery step 2 |

Selection rules that outrank the shelf: **never stack two frameworks** in
one harness — registration orders interact and the same slot gets
double-hooked; the nondeterminism that follows costs more than every
individual choice on the shelf. Pick one slot per gap class, and keep the
comparator channel on the device side.

## Install timing matrix

**Family: install-timing discipline (loader/init-window vocabulary)**

| Install window | What it can catch | Evidence | Variant inspiration |
|---|---|---|---|
| Before load (registered ahead of module load) | Init-time import calls — PLT-class registration MUST precede first use; a late registration silently never fires | 1 queue source | Register-before-first-use: same lesson as the file resolver registered before library load (unidbg-env-filling) |
| After load, before init-array/JNI_OnLoad runs | Init-time behavior with post-init noise excluded — the windowed-latch posture from dynamic-observation-ladders applied to the harness | 1 queue source | Windowed latch — observation windows, not global switches |
| After init completes | Post-init business calls only; init-time gaps become invisible (they already ran unanswered) | 1 queue source | Late-attach blindness: what already ran cannot be observed retroactively |

## Bring-up failure signatures

**Family: substrate-failure decode (failure-signature vocabulary)**

| Failure signature | Do this first | Evidence | Variant inspiration |
|---|---|---|---|
| PLT-class hook fires for the earliest calls, then goes permanently silent | Import-refresh escape: the library re-resolved or re-patched its import slots after registration (late-loaded dependency, self-refresh, anti-hook sweep), dropping the redirect. Move to symbol-level inline hook (survives refresh by construction) or re-register after the refresh point | 1 queue source (explicit signature) | A snapshot-bound mechanism escapes by invalidating the snapshot — interpose below the snapshot layer instead of re-arming it |
| Instruction hook ignored or faults only on the fast backend | The JIT-class backend does not support per-instruction code hooks — instruction-level work requires the default backend; re-choose per the backend trade (run-fast vs analyze-deep) | 1 queue source | Capability is backend-bound, not tool-bound — same channel-descent logic as observation channels |
| Harness hang right after a thread-dispatch call, no further log | The dispatcher waits on a queued thread body the single-thread backend never schedules — force the queued body inline (or cap dispatch depth) rather than chasing the wait chain | 1 queue source | Hang-on-dispatch: fix the scheduler assumption, not the waiter |
| Packed SO: loader dies inside the unpacking stub, or unpacks and then fails its own self-check under emulation | Dump-then-load (below) instead of re-fighting the packer | 1 queue source | Skip the gate you cannot answer; carry the state past it |
| Packed SO loads but exports resolve to nothing usable | Same move — the on-disk form is not the real code; get the loaded form | 1 queue source | The loaded image is the ground truth, not the file image |

## Dump-then-load (artifact acquisition when the on-disk form cannot run)

**Family: artifact acquisition (loader vocabulary)**

When the target SO is packed/self-decrypting, loading the on-disk artifact
into the emulator makes YOUR harness run the packer — where its
anti-emulation checks and device assumptions fail. Move: let a real runtime
unpack it once, dump the decrypted artifact from memory at init-complete,
and load THAT into the harness.

- **The dump is the loaded state, not the file image**: relocations applied,
  possibly re-based — symbol addresses move relative to the on-disk layout.
  Every static read (constants, call targets) must be taken against the
  dump's layout.
- The dump is target-version-bound: an app update invalidates it; re-dump
  per target version and record the version in the workspace note.
- Dumped form removes the packer's runtime behavior — anything the target
  READS from its own unpacking (self-integrity data) needs an explicit
  environment answer per unidbg-env-filling.

### Few-shot — the PLT hook that went quiet (synthetic)

```python
# early calls logged, then silence; the library still calls the symbol:
run_once()               # hook fires
run_more()               # hook silent — but the syscall IS happening
# decode: registration bound to the import snapshot at install time;
# a late-loaded dependency re-resolved the slot. Re-registering at the
# same layer re-arms the same trap. Move DOWN one layer: inline-hook the
# symbol itself (prologue patch survives import re-resolution), or find
# the refresh point (late dlopen/dlsym) and re-register after it.
```

## Closure summary

| Gate | Minimum evidence |
|---|---|
| Slot chosen | Gap class named; the choice justified against the shelf (candidates do not interchange) |
| Timing picked | Install window matches what the gap needs to catch (init-time vs post-init) |
| Silent-hook decode | Refresh-escape named (or ruled out) before re-arming the same mechanism |
| Artifact running | On-disk vs dumped form decided; dump layout recorded as the read baseline |

## Cross-references

- The environment answers this substrate enables: [unidbg-env-filling.md](unidbg-env-filling.md)
- The loop the running harness feeds (order heuristic, per-stub validation, closure gates): [native-sign-recovery.md](native-sign-recovery.md)
- Device-side channels and their costs: [tools-dynamic.md](tools-dynamic.md)
- Device-side detection doctrine the packed stub may carry: [anti-analysis.md](anti-analysis.md)
