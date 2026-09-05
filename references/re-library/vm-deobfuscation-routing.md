---
name: vm-deobfuscation-routing
description: Routing gate for obfuscated targets in two lanes — (A) screening RAW minified JavaScript BEFORE deobfuscation to decide whether it carries a custom bytecode VM, with a negative-exclusion table that routes WASM, embedded-WASM, bundler, and mis-labeled-binary shapes away from the JS-VM lane, and (B) classifying native control-flow-flattening VARIANTS from the decompiled dispatcher shape, because "flattening" is a family of adversaries whose countermeasures do not interchange. Use when a target arrives as opaque one-line JS or as a flattened native binary and the first decision is which recovery lane to enter.
---

# VM & Deobfuscation Routing (pre-unpack JS screening + flattening-variant ecology)

> **Quality-gate warning (read first).** Obfuscator ecosystems evolve fast and
> countermeasure tools break across generations. This card lands ONLY the
> stable layer — discrimination cues and countermeasure CATEGORIES — and
> deliberately omits tool names, versions, and rankings. Tool selection is an
> execution-time re-search task, never a card lookup. This is not an
> omission shortcut: the material behind this card carried heavily outdated
> tooling, and carrying it forward would be exactly the "stale information
> poisoning priors" failure the distillation quality gate exists to prevent.

## When to Use

- A target arrives as raw minified/one-line JavaScript and the first decision
  is: custom JS VM, embedded WASM, ordinary bundle, or binary mis-saved as text?
- A native function decompiles into a loop-driven state machine and the next
  decision is which countermeasure family applies — judging the variant wrong
  makes every downstream countermeasure wrong.

## Part A — pre-unpack JS screening (raw form, BEFORE deobfuscation)

### Positive features (true custom JS VM — all lean the same way)

| Feature | Shape |
|---|---|
| Entry | IIFE wrapper; dense single-letter locals initialized from numeric-constant mappings |
| Interpreter loop | one function holding `for(;;)` + `switch` whose operand is decoded from bitfields (`v & 31` opcode, `v >> 5 & 31` sub-op — exact bit layout varies; the *presence of bit-decoding* is the invariant) |
| Constant tables | `C[index]` accesses feeding calls — function/string tables reached only by index, never by name |
| Byte statistics | large file with near-zero share of zero bytes — pure JS text, not a binary |
| Formatting | single-line minification (packer output, not source) |

### Negative exclusion table (routing wrong here = everything after is wrong)

| Observation | Ruling | Route |
|---|---|---|
| `\x00asm` magic at offset 0 | standard WASM | binary lane — NOT the JS-VM lane |
| `Uint8Array([0,97,115,109])` literal mid-file | embedded WASM | carve out to `.wasm`, hand to a decompiler |
| `function(e,t,n){...}` three-arg module factories | standard bundler packaging | ordinary bundle-restoration lane (unbundle + deobfuscate passes) |
| High zero-byte share | binary content mis-labeled as JS | re-triage the artifact, not the text |

The exclusion table runs FIRST and its hits are terminal for the JS lane —
an exclusion hit is a routing answer, not a weak signal.

### Confirmed as a JS VM — first three moves

1. Locate the dispatcher (the switch main loop).
2. Read the bitfield encoding — which bit ranges are opcode, sub-op, operand.
3. Classify the constant table — which index ranges hold functions, which
   hold strings; that boundary is what every later trace depends on.

**Handoff.** This card screens the RAW form. [jsvmp-triage.md](jsvmp-triage.md)
three-feature voting applies only to ALREADY-DEOBFUSCATED bundles: run it
after unpack/deobfuscate, with this card's verdict as the reason you got there.

## Part B — flattening-variant ecology (native face)

**Core thesis: "flattening" is not one adversary.** Variant families —
descended from different obfuscator generations — look similar in a
decompiler and take non-interchangeable countermeasures. Devirtualizing a
VM-ized target with flattening-class tooling burns days; the label comes
first, always.

### Variant discrimination cues, countermeasure categories, falsifiers

| Variant | Discrimination cue | Countermeasure category | Falsifier (how the label dies) |
|---|---|---|---|
| Basic three-pass family (flattening / bogus control flow / instruction substitution) | state variable + dense 0..N switch in a loop; opaque predicates; MBA-style arithmetic rewrites | IDE-plugin-class deflattening + expression simplification | single-step several state transitions: progression matches the predicted dense order → keep; sparse or wide-jump → re-classify |
| Indirect-branch dispatcher | loop head dispatches via computed indirect jump, no switch | make the branch-target data section read-only so jump targets become statically solvable | forcing the "target table" static yields garbage or runtime-rebuilt values → not this variant |
| Constant-encryption type | literals never appear as true values statically; every use is preceded by a decode stub | execute the decryption stub dynamically once, then read the plain values | no decode stub, or constants arrive already plain at first use → label unsupported |
| VM-ized (control flow became a dispatch loop) | handler table + program counter; case bodies are semantic-free | NOT a flattening problem — handler-table recovery (trace → opcode map → replay) | trace shows no handler-table anatomy; state stays dense-small → return to the flattening rows |
| Anti-symbolic-execution type | features that punish symbolic engines: path-explosion traps, solver-hostile opaque predicates | constraint-then-solve scripting with targeted path pruning | concrete execution diverges from the solver-model prediction of state transitions → the symbolic-hostile reading is wrong |

Every variant judgment names its falsifier at admission — the judgment is a
hypothesis, not a fact (same rule as the obfuscation-variant family in
[falsifier-library.md](falsifier-library.md)).

### Countermeasure selection order (categories, never tool names)

1. **IDE-plugin class** — local, open-source, covers multiple variants. First.
2. **Cloud-plugin class** — strongest effect, but needs network + closed
   source; weigh the sandbox/opsec cost before use.
3. **Symbolic-execution script class** — when no GUI/disassembler session
   exists.
4. **Custom handler recovery** — VM-ized exclusive; do not attempt it on the
   other variants.

## Few-shot — dispatcher recognition checklist (synthetic)

```bash
# ordered checks over the raw minified JS; cheap terminal negatives FIRST
python -c "d=open('f_raw.js','rb').read(); print(d[:4], round(d.count(0)/len(d),4))"
#   b'\x00asm' 0.0            -> standard WASM: binary lane, STOP
#   other magic, ratio high   -> binary mis-saved as text: re-triage, STOP
grep -c 'Uint8Array(\[0,97,115,109\])' f_raw.js   # >0 -> embedded WASM: carve to .wasm, STOP
grep -c 'function(e,t,n){' f_raw.js               # high -> bundler module factories: bundle lane, STOP
# JS-VM positives, in evidence order:
grep -c 'for(;;)' f_raw.js                        # >=1 candidate interpreter loop
grep -oE '[a-z]>>5&31|[a-z]&31' f_raw.js | sort -u  # bitfield decode hits -> opcode/sub-op split
grep -oE '\b[a-z]\[[0-9]{1,4}\]\(' f_raw.js | head  # C[index]( calls -> indexed function table
```

## Few-shot — variant discrimination skeleton (synthetic)

```python
def classify(shape, trace):
    # called on the DECOMPILED dispatcher; unclassified is a legal output
    if shape.has_switch and state_dense_0_to_N(shape):
        return "basic-three-pass"   # falsify: step 5 transitions; order must stay dense
    if shape.indirect_jump and shape.target_table:
        return "indirect-branch"    # falsify: force-resolve targets; garbage -> not this
    if constants_statically_opaque() and decode_stub_precedes_use():
        return "constant-encrypted" # falsify: no stub / plain at first use -> unsupported
    if shape.handler_table and trace.pc_indexing:
        return "vm-ized"            # falsify: no handler anatomy on trace -> flattening rows
    if solver_time_explodes() and concrete_runs_fine():
        return "anti-symbolic"      # falsify: concrete vs model divergence -> re-read
    return "unclassified"           # do NOT force a row; unclassified asks for more evidence
```

## Closure summary

| Gate | Minimum evidence |
|---|---|
| Lane chosen | Negative-exclusion table executed (WASM / bundler / binary ruled out) before any JS-VM claim |
| Dispatcher read | Bitfield layout + constant-table classification written down |
| Variant labeled | A named falsifier per variant judgment; the label survives its experiment |
| Countermeasure picked | Category chosen by the selection order AFTER the variant label, tools re-researched at execution time |

## Cross-references

- Deobfuscated-form VM triage (three-feature vote): [jsvmp-triage.md](jsvmp-triage.md)
- Variant-judgment falsifier family: [falsifier-library.md](falsifier-library.md)
- Concrete flattening/MBA countermeasure patterns (tool-level, verify currency): [anti-analysis.md](anti-analysis.md#control-flow-flattening-advanced)
- Flattening inside a sign-recovery ladder: [native-sign-recovery.md](native-sign-recovery.md)
- Unpacking before this card applies: [stacked-protections.md](stacked-protections.md)
