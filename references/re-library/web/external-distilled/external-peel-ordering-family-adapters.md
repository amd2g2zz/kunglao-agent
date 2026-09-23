---
name: external-peel-ordering-family-adapters
description: 'Multi-pass deobfuscation ordering and family-adapter discipline (external-distilled, S2/S6):
  pass-ordering contract (each pass expects the previous pass''s output shape), re-detect after every unpack,
  residue metrics driving generic-vs-family adapter layering, per-family pass reordering, decoder-indirection
  escape hatch, eval-safety gate for untrusted packed input, bundle entry-selection fan-out sanity and the
  false-completion trap. When a peel chain silently no-ops, when generic deobfuscation stalls on a specific
  obfuscation family, or when choosing the entry chunk of a multi-chunk bundle.'
domain: web
family: external-distilled
source_id: S2,S6
source_license: MIT,none
retrieved: 2026-09-23
epistemic: external-derived
distill_bar: general+heuristic
dedup: overlap(web-re-quickref layered peeling)
---

# Peel ordering & family adapters (external-distilled)

> External-derived methodology (never directly PROVEN). Generalized paraphrase;
> provenance = S-id list above. The peel LOOP (inspect → route → transform →
> re-inspect) and the bundler/obfuscator routing table are web-re-quickref's;
> this card lands what happens INSIDE a pass chain and how per-family residue
> is engineered, which the loop card does not cover.

## The pass-ordering contract

A deobfuscation chain is a sequence where each pass expects the input SHAPE
the previous pass produced. Out-of-order runs do not error — they silently
no-op or mangle, which is worse. The contract generalizes:

- **Unwrap execution-form first.** Packed/self-decoding wrappers are one
  giant call expression until unwrapped; AST-level passes have nothing to
  grip. Unwrap before any structural pass.
- **Resolve the string table before literal passes.** Inlining the string
  array first lets literal-decoding passes walk only used literals, and
  constant folding works on resolved literals. Folding FIRST can rewrite the
  rotation wrapper into a shape the string-array matcher no longer
  recognizes.
- **Structural reporting LAST.** Control-flow reports must run after
  constant-folding has eaten the fake-branch residue, or the report describes
  noise.
- **Byte-rewriting passes invalidate downstream artifacts.** Any pass that
  rewrites bytes (unwrapper, transpiler-normalizer) invalidates recorded
  positions/ids from earlier passes — re-derive them after, never reuse.
- **Re-detect after every unwrap.** Unwrapping reveals the layer underneath
  (our loop card's "layers hide under layers", from the mechanical side):
  re-run detection after each unwrap and let the detector, not memory, pick
  the next pass.
- **Per-pass fault isolation.** Wrap each pass so one failure does not abort
  the chain — a pass that throws still leaves the earlier passes' output
  usable.

**Decoder-indirection escape hatch:** when string-table access is wrapped in
a decoder function, direct inlining fails. Inline the small wrapper functions
first (a simplification pass), then re-run the string-table pass — order the
retry, do not conclude "unrecoverable".

**Eval-safety gate:** unwrapping packed input executes it by construction
(the decoder runs). Treat unwrapping as untrusted-code execution: sandbox
isolation for the pass, or an explicit no-eval refusal mode that leaves the
input unchanged and says so. Never unwrap unvetted input in a privileged
runtime.

## Residue metrics drive the adapter layer

Generic passes stay generic (structure normalization, dead-branch removal,
constant folding). Site/family-specific quirks live in SEPARATE adapter
passes, and the separation is enforced by evidence, not taste:

- **Measure the residue.** After the generic chain, count what is still
  undigested (string-table access patterns, flat dispatch remains, opaque
  predicates, obfuscator-name density). The residue profile IS the family
  fingerprint.
- **Family adapters enter only on evidence.** A family-specific adapter
  (rule doc + detector signature + targeted script + pipeline entry) is
  written when a pattern recurs; a one-sample quirk stays a one-off script
  and does NOT graduate into the generic chain until it proves out on
  unrelated samples.
- **Reorder expensive passes per family.** High-cost passes run where the
  family needs them, not in a universal order — running literal inlining
  late on a huge sample can stall the whole chain; families that do not need
  a pass skip it.
- **Every structural rewrite re-parses.** After each transforming pass the
  output must re-parse cleanly, and each pass must run standalone for
  debugging — a chain that only works end-to-end is undebuggable.

## Entry selection & the false-completion trap

For multi-chunk bundles, choosing WHERE to start has its own failure mode:

- **Sourcemap before sweat.** If a source map exists, recovering original
  sources beats any renaming pipeline. Check first, always.
- **Fan-out sanity check on the entry.** The real application entry has
  LARGE local fan-out and approximately nobody imports it; a vendor leaf is
  the exact inverse. Sanity-check the chosen entry against this shape before
  restoring from it.
- **The false-completion trap:** restoring from a transitive vendor leaf
  yields a small closure that LOOKS complete — a handful of files, all
  resolved, nothing missing — while the actual application tree sits
  unexplored. "Everything I touched resolved" is not "the tree is done".
  Anchor on the host page's script graph or a high-fan-out chunk, and let a
  graph walk (not file count) define completion.

Companions: [web-re-quickref.md](../labs/web-re-quickref.md) (peel loop +
routing table), [jsvmp-triage.md](../vm/jsvmp-triage.md) (VM boundary stop
condition), [vm-deobfuscation-routing](../../patterns/vm/vm-deobfuscation-routing.md)
(lane gate).
