---
name: jsvmp-triage
description: JSVMP/VMP bytecode-VM triage for deobfuscated web bundles. Use when a deobfuscated bundle may hide a bytecode VM (big consumed array + dispatch-switch loop + stack-op handlers), to decide between continuing AST-level recovery and switching to the instruction-trace methodology, or to interpret a jsvmp-triage CLI verdict (votes/confidence).
domain: web
family: vm
---

# JSVMP/VMP Triage (three-feature, three-of-two)

Advisory static heuristic over ALREADY-DEOBFUSCATED bundles (wakaru/webcrack
output). Answers one question mechanically: does this bundle carry a bytecode
VM, so AST-level recovery should STOP and the operator should switch to the
instruction-trace methodology? It is NOT proof; runtime trace confirmation
stays with the operator.

Executable face: `tools/web/jsvmp_triage.py`, registered as `jsvmp-triage`
(capability `web:triage`, category `web`, `tools/_INDEX.yaml`).

## When to Use

- After unbundle/deobfuscate (`npx wakaru --unpack`, `npx webcrack`), before
  burning more AST passes on a bundle that cannot yield to AST recovery.
- To interpret a CLI verdict: `vmp_suspected` ⇔ votes ≥ 2 of {F1, F2, F3};
  confidence high (3/3) / medium (2/3). A 2/3 "medium" on a bundle you
  believe clean is a prompt to read the named signals, not to rerun.

## Three-feature thresholds

| Feature | Signal | Threshold | CLI field |
|---|---|---|---|
| F1 | big consumed integer/string array | ≥ 100 literal items (`MIN_ARRAY_ITEMS`) | `f1_bytecode_array` |
| F2 | dispatch switch in an infinite loop | ≥ 8 distinct numeric cases (`MIN_CASE_COUNT`); `pc_indexing` = `ptr++` indexing into the table | `f2_dispatch_loop` |
| F3 | semantic-free case bodies | ratio ≥ 0.9 **and** a case table exists (`case_bodies_found`) | `f3_semanticless_handlers` |

Verdict semantics (#884): `votes = F1 + F2 + F3`; suspected ⇔ votes ≥ 2;
confidence high (3/3) / medium (2/3) / low. F3 is anchored on
`case_bodies_found` — with no case table the ratio reads 1.0 by absence, and
absence must not vote (the big-array-alone tripwire pins this).

## Why three-of-two, not F1∧F2

The pre-#884 gate `confident = f1 and f2` silently missed two pairings with
documented real-world shapes: bundles carrying the array + handler anatomy
but a non-canonical loop head ({F1,F3}), and dispatch-table-heavy bundles
whose string array was reclaimed or below threshold ({F2,F3}). Three-of-two
keeps the single-feature lanes (array-only, dispatch-only) at "low".

## Methodology outline (trace / OPCODE_MAP / replay)

The triage verdict only opens the door. The instruction-trace methodology
(#816, CP1→CP3) that follows it:

1. **Confirm at runtime (CP3)** — single-generation complete opcode/stack
   trace: hook the dispatch loop's switch operand and the stack ops, dump
   one full generation, save the trace as the opcode semantic ground truth.
2. **Build the OPCODE_MAP** — from the trace, map each opcode (case index)
   to its stack effect (pops/pushes/peeks) and side effects; two opcodes
   sharing a case body are the same opcode; handlers calling into native
   APIs are boundary opcodes worth their own entries.
3. **Replay / verify** — re-execute the bundle's logic against the map in a
   controlled interpreter (or re-derive a target computation offline) and
   diff against observed behavior; replay matching the trace is the
   mechanical gate for "semantics recovered".
4. **Then** recover the business logic on top of the recovered semantics
   (decompile handlers into pseudo-instructions, name by stack effect, and
   only then re-attach to the surrounding AST).

Advisory posture: this card is methodology guidance, not a proof artifact —
verdicts are evidence to verify, same discipline as every other kunglao
output (maker-checker applies to your own triage reading too).

## Vendor-verified instance: the sensor-VM anatomy

**Family: instruction-trace methodology, vendor-verified face (queue
cluster: web; verified against real shipped code, not docs)**

The hardened anti-bot sensor VMs (request-sensor blob producers behind
interstitial challenges) are the JSVMP shape at production hardness — this
instance adds three mechanics the generic outline above does not name, and
serves as existence proof that the trace → opcode → lifter route survives
them:

- **Property-resolution memory model.** Property access inside the VM goes
  through a resolution layer that records HOW a value was reached, not just
  the value — resolution order, absence, and the path taken are all
  observable state. Practical face: hooking the property GETTER answers the
  value but blinds the resolution metadata; the observation point is the
  resolution path itself (the VM's own access helper), and an environment
  that answers values without reproducing resolution behavior diverges on
  the next consistency check.
- **Exit via a nonexistent opcode.** The generation loop terminates by
  dispatching an opcode index with NO handler — a tamper exit, not a
  normal termination. Signature: the trace ends mid-generation at an
  unmapped opcode. Practical face: instrumentation that forces extra
  iterations, and any lifter that assumes handler totality, both die
  there; treat the unmapped-index exit as the VM saying "observed", and
  capture around it (split the generation, or let that exit pass through
  unmodified) instead of "fixing" it.
- **Trace → opcode → lifter → CFG, end to end.** The vendor-verified
  pipeline for business-logic recovery: (1) capture one complete
  generation trace; (2) build the opcode map per the methodology outline
  above; (3) write a lifter — case bodies become pseudo-instructions, the
  stack discipline from the opcode map gives each one its signature;
  (4) lift the generation to a CFG — the sensor-field assembly becomes
  readable as dataflow over the CFG, which is what makes the output
  reproducible offline.

Scope boundary (do not overclaim): the sensor blob's serialized FIELD
LAYOUT is publicly documented at pointer level only — field names and
ordering circulate as unverified claims. Treat any format assertion as a
prior to verify against a live capture before building a serializer; this
card lands the anatomy and the pipeline, not a field map.
