# Tasks — issue #751

## T1 Capability vocabulary
- [x] T1.1 Add `js:semantic-query` + `js:call-graph` to `_CAPABILITY_TAGS`
      (tools/validate_index.py); refresh the stale #728 coordination comment.
- [x] T1.2 tests/test_gitnexus_web_751.py: vocabulary assertions + shipped
      index still validates.

## T2 Registry entry
- [x] T2.1 gitnexus-query: produces += js pair; quality += high/high;
      input_output + when_not state js source_tree semantics (wakaru/webcrack
      output dir; evidence unpack_out hand-off).
- [x] T2.2 wakaru-unbundle / webcrack-deobfuscate input_output note the
      unpack_out registration gap (#760 consumes it).
- [x] T2.3 tools/_index-static.md H3 entries synced.
- [x] T2.4 Annotation-schema tests (#692 shape) in the new suite.

## T3 Quickref index step
- [x] T3.1 references/re-library/web-re-quickref.md layered-peeling section:
      post-recovery `gitnexus analyze <out_dir>` + signature-trace query
      posture (English-only, six-section contract preserved).
- [x] T3.2 re-pin references/_INDEX.yaml (scripts/re_pin_references.py).

## T4 Route linkage
- [x] T4.1 Verify + pin capability_matches / resolve_capability genericity
      for js: tags against the shipped registry.
- [x] T4.2 Fixture trigger table (tests/fixtures/web751/specialists/
      gitnexus-query.md) + routing test: fixed claim → gitnexus-query under
      the fixture table; no mis-route under today's real table.

## T5 Real-sample demo
- [x] T5.1 tests/fixtures/web751/bundle.min.js (+ readable source, runnability
      check in-script).
- [x] T5.2 tools/static/web_gitnexus_demo.py — three-leg pipeline with
      structured SKIP degradation + node self-check; evidence JSON output.
- [x] T5.3 Golden of the REAL local run committed
      (tests/fixtures/web751/evidence-demo.json).
- [x] T5.4 release-manifest.yaml asset declaration.

## Quality gates
- [x] G.1 Targeted suite green (test_gitnexus_web_751 + validate_index +
      ext_index + tool_search + 728/692 touchpoints).
- [x] G.2 Sanitized-PATH full pytest run green.
- [x] G.3 release receipt --check + devkit quality_gates.
- [x] G.4 ruff on changed files.
