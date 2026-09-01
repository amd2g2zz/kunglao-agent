---
name: jsvmp-triage
description: JSVMP/VMP bytecode-VM triage for deobfuscated web bundles. Use when a deobfuscated bundle may hide a bytecode VM (big consumed array + dispatch-switch loop + stack-op handlers), to decide between continuing AST-level recovery and switching to the instruction-trace methodology, or to interpret a jsvmp-triage CLI verdict (votes/confidence).
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
