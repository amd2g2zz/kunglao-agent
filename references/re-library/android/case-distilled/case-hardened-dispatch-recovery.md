---
name: case-hardened-dispatch-recovery
description: 'Boundary discovery + static recovery of computed dispatch in hardened Android native
  libraries (case-distilled, internal campaign D1): export-surface triage, RegisterNatives capture via
  the JNIEnv vtable, op dispatcher identification by constant census, computed indirect-call resolution
  through relocation folding with execution verification, return-slide patching, branch-gadget
  interpretation, and flattened-FSM walk. Use when a stripped native library hides its handler table
  behind computed calls, decoy bytes, or control-flow flattening.'
domain: android
family: case-distilled
source_id: D1
source_license: internal
retrieved: 2026-09-23
epistemic: evidence-derived
distill_bar: general+heuristic
dedup: overlap(vm-protection-anatomy handler-table recovery; vm-deobfuscation-routing lane B)
campaign_cluster: C7,C1,C3 (+I42 from C8, I44/I83/I86 cross-cluster)
---

# Hardened dispatch recovery (case-distilled)

> Internal-campaign distillate (evidence-derived; provenance = D1 cluster
> C7/C1/C3, item ids in the wave gap report). Generalized paraphrase; every
> concrete address, opcode, constant, and library name is a `<placeholder>`.
> vm-protection-anatomy owns the build-side/peel-side ANATOMY map; this card
> owns the mechanical RESOLUTION ladder — the situation→action rules and the
> verification order that turns an opaque dispatcher into a named handler
> table.

## Why this order (planning layer)

The campaign resolved a fully stripped, computed-dispatch library in this
sequence: boundary (Java entry → native dispatcher address) → one handler
(validate the resolution method on a single case) → full table (automate) →
handler bodies (patch slides, re-decompile). Each step existed because the
previous step produced the constant the next one needs: the dynamic capture
supplies the ground-truth dispatcher address that validates the static fold;
the single validated fold supplies the tuple shape that the batch extraction
regexes; the full table supplies the targets the slide-patcher visits.
Starting anywhere else (batch-fold first, or handler bodies first) has no
ground truth to check against — every downstream artifact would be uncheckable.

Verdict algebra for the whole lane:
`handler-table-recovered ⇔ every table entry resolves to an address whose
disassembly prologue is plausible ∧ ≥1 entry validated against a runtime
observation`.

## Boundary discovery

```c
// stripped .so triage: exports tell you the registration mode
//   only JNI_OnLoad, zero Java_ symbols  → RegisterNatives dynamic registration
//   → the Java-side entry class comes from a dex package census, not from symbols
```

| Situation | Action |
|---|---|
| runtime does not export the registration symbol at all | hook the JNIEnv function table at the fixed ABI index for `RegisterNatives`; filter registered fnPtrs inside the target module range |
| need the dispatcher's semantic contract | read the registered signature: `(opCode, flag, handle, str, obj)` shape = one choke point for all ops; that function is the best single capture point |
| instance state across the boundary | instances travel as integer handles; `handle == -1` means uninitialized — never interpret output from an uninitialized handle |
| a hook framework API moved in a major version | pin API usage per version; wrap module lookups in try/retry (modules may load late) |

Why vtable-index hooking: symbol-based routes return empty *silently* — an
empty enumeration is the failure signature of "symbol not exported", not
"nothing registered". The vtable slot is ABI-stable regardless of export
policy.

## Dispatcher identification + computed-call resolution

Identify the dispatcher statically by constant census, then resolve every
computed call:

```text
fold(pc) = ((~pc & M1 | C1) + (pc & M2 | C2)) ^ K      # pc = dispatcher EA
handler  = RELA_addend(table_entry_vaddr) + fold(pc)    # R_AARCH64_RELATIVE
```

| Situation | Action | Why |
|---|---|---|
| candidate function references the full known op-constant range and branches numerically | that is the dispatcher | partial ranges are per-op wrappers |
| indirect call reads a table whose file bytes are zero | parse the relocation section; use each entry's addend as the base | relative read-only data is late-filled — file bytes are reliably wrong, not accidentally |
| fold result lands outside the image, or looks wrong | verify by EXECUTION (emulate the few fold instructions, read the result register) | hand arithmetic failed once at real cost; execution of 12 instructions is the checker (see E-correction in gap report) |
| table addends exceed image size | expected — deliberate out-of-image bases folded back in | a script assuming in-image entries breaks here |
| candidate handler address found | confirm the disassembly prologue (frame setup + platform guard register) before trusting it | the fold is arithmetic; the prologue is semantics |

## Slides, gadgets, decoys — reading handler bodies

| Situation | Action |
|---|---|
| decompiler output shows a self-call passing its own address plus a small constant | decode as a BRANCH GADGET: `return-to(link-register + arg)` — runtime-computed PC-relative skip, not recursion, not keying |
| pseudocode shows a call with computed operands that disassembly says is data (`.inst` words) | the call is a DECOY rendered from dead bytes; disassembly is ground truth, pseudocode advisory |
| handlers end mid-flow into `adr/mov lr/ret` runs | patch the slide in a COPY of the binary to continue at the slide target; one patch script restored decompilation for every handler |
| function at a known offset is absent from auto-analysis | `add_func` then decompile; auto-decompilation fails SILENTLY on undefined functions — absence of output is analysis state, not absence of code (see [ida-scripting-overlays](../../method/process/ida-scripting-overlays.md)) |
| decompiler still fails (register threading across blocks) | read disassembly; the campaign's terminal chain reads came from disassembly everywhere slides existed |

## Flattened-orchestrator walk

When a function is control-flow-flattened rather than dispatched:

```text
1. find the state register (single register compared against many constants)
2. collect the state-code constant multiset          # these are fingerprints —
                                                     # see constant-fingerprint card
3. walk the compare/branch chain from the initial state
   → true execution order falls out as an FSM
4. do NOT classify as a bytecode VM without a fetch/decode loop
```

Why the FSM distinction matters: a flattened orchestrator walks in one static
pass; a bytecode VM needs the trace methodology
([jsvmp-triage](../../web/vm/jsvmp-triage.md) for the JS face,
[vm-protection-anatomy](../../patterns/vm/vm-protection-anatomy.md) for the
native face). Misclassifying sends you to trace-capture work that static
reading would have solved in an afternoon — and vice versa.

## Companions

[unidbg-algo-recovery](../emulation/unidbg-algo-recovery.md) (emulator-side
verification moves), [case-kill-evidence-counterplay.md](case-kill-evidence-counterplay.md)
(what you may hook once handlers are known),
[case-constant-fingerprint-attribution.md](case-constant-fingerprint-attribution.md)
(reading the constant multiset you just recovered).
