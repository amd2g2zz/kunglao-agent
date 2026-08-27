# Web JS semantic index layer — gitnexus over wakaru/webcrack output (#751)

## Why

Issue #751: the #728 web labs gave JS targets two recovery pipelines —
wakaru-unbundle (`js:unbundle`) and webcrack-deobfuscate (`js:deobfuscate`)
— but nothing AFTER recovery. Locating symbols and chasing call chains in
the unpacked tree is manual grep. The android side (#692) already routes
this class of question through gitnexus-query (android:semantic-query +
android:call-graph). gitnexus natively parses JS (Tree-sitter), and
wakaru/webcrack output is ordinary JS source, so the query layer extends to
the web domain with zero adaptation.

## What Changes

- **Capability vocabulary (T1)**: `js:semantic-query` + `js:call-graph` join
  the Rule B closed `_CAPABILITY_TAGS` vocabulary (tools/validate_index.py).
  Deliberate review decision recorded here: one tag = a distinct routing
  capability; the js tags mirror the android pair so signature-tracing
  claims route identically on both domains.
- **Registry entry (T2)**: the existing `gitnexus-query` entry grows the two
  js produces tags (quality high each) — one provider covers both domains;
  `requires: [source_tree, gitnexus_index]` semantics are written out:
  for the js domain `source_tree` is satisfied by a wakaru/webcrack output
  directory. wakaru-unbundle / webcrack-deobfuscate entries note that their
  output directory is registered into `evidence/<run>.json` under
  `unpack_out` (the hand-off anchor the lazy index builds from).
- **Quickref step (T3)**: the layered-peeling section of
  references/re-library/web-re-quickref.md gains an explicit post-recovery
  step: `gitnexus analyze <out_dir>` → semantic queries for
  signature-tracing posture (which function assembles the signature string →
  what does it call → which request entry reaches it). Methodology only;
  the execution carrier is the #760 worker contract.
- **Route linkage (T4)**: verify capability_matches / resolve_capability
  already resolve js: prefix tags generically; pin the specialist-routing
  contract for gitnexus-query intent triggers (semantic/xref/call graph/
  调用链/谁调用 paraphrases) via fixture trigger table. See design.md D2 —
  no agent file ships from this wave.
- **Real-sample demo (T5)**: tools/static/web_gitnexus_demo.py — bundled-JS
  fixture → webcrack/wakaru recovery → `gitnexus analyze` → semantic query
  answering "find buildSignature's caller". Platform/network-degraded legs
  SKIP with structured reasons; offline the script self-checks.

## Capabilities

### Modified
- `capability-registry`: js-domain adds to the closed vocabulary + the
  gitnexus-query provider entry (+ wakaru/webcrack evidence hand-off notes).

## Impact

- tools/validate_index.py (vocabulary constants only)
- tools/_INDEX.yaml (one entry extended, two entries' input_output notes)
- tools/_index-static.md (doc sync)
- references/re-library/web-re-quickref.md + references/_INDEX.yaml re-pin
- tests/test_gitnexus_web_751.py (new suite)
- tests/fixtures/web751/* (demo fixtures)
- tools/static/web_gitnexus_demo.py (demo/regression script)
- release-manifest.yaml (asset declaration)
