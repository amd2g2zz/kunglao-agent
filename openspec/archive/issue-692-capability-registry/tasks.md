# Tasks — Android capability-provider registry (#692)

## 1. Setup

- [x] 1.1 Worktree `D:/codebase/kunglao-issue-692-capability-registry` branch `issue-692-capability-registry` off origin/dev (60fb295 — contains #680 ToolMeta 1005266, #662/#663/#669/#670 landing)
- [x] 1.2 Baseline recon: _INDEX.yaml (30 entries, no provider annotations, no jadx/baksmali/apkid/gitnexus entries), route_capability (no provider pass), dispatch_context (no providers key), mcp_probe (gitnexus already android HARD), smali_index.json gitnexus-shape wire, dex-decompiler upstream facts verified (module `dex_decompiler`, CLI `dex-decompile`, `--taint-api/--taint-solve/--taint-output` IssueReport)

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 proposal.md
- [x] 2.2 design.md (D0 matrix = contract core; D1-D10)
- [x] 2.3 specs/capability-registry/spec.md
- [x] 2.4 tasks.md

## 3. WP1 — capability annotations (commit 1)

- [x] 3.1 RED tests/test_index_capability_annotations.py (annotation lint rules D1.1-3 on synthetic index; shipped index has the 4 new provider entries with well-formed annotations)
- [x] 3.2 tools/validate_index.py: annotation structural checks
- [x] 3.3 tools/_INDEX.yaml: jadx-decompile / baksmali-xref / apkid-prescan / gitnexus-query entries + annotations
- [x] 3.4 tools/_index-static.md rows; CHANGELOG v0.1.3 append
- [x] 3.5 RED->GREEN captured (RED: 11 failed/3 passed; GREEN: 14/14 + tool_search pins 29->33, 26->27 updated deliberately)

## 4. WP2 — dexdc provider (commit 2)

- [x] 4.1 RED tests/test_dexdc_scanner.py (9 failed captured) (index+taint schemas D6, detection fail-open, UTF-8 guard, landing-checklist asserts)
- [x] 4.2 tools/static/dexdc_scanner.py (PyO3-first, CLI fallback, evidence writers)
- [x] 4.3 scripts/toolchain.py: FIXES["dexdc"] ToolMeta + NextAction (#680 pattern)
- [x] 4.4 tools/_INDEX.yaml dexdc-decompile entry; release-manifest.yaml asset; tools/_index-static.md row (receipt --check exit 0; tool_search pin 33->34)
- [x] 4.5 RED->GREEN captured (9/9; toolchain/baksmali/apkid/mem_gate suites 72 passed)

## 5. WP3 — provider selection (commit 3)

- [x] 5.1 RED tests/test_route_capability_providers.py (10 failed captured) (two-state acceptance 2; failure-memory acceptance 4)
- [x] 5.2 scripts/provider_health.py (record/query, fail-open)
- [x] 5.3 scripts/route_capability.py: load_workspace_state + select_providers + --capability CLI (providers ride the --capability direct query; route() feature flow unchanged)
- [x] 5.4 RED->GREEN captured (10/10; route/specialist/dead_code suites 47 passed, no regression)

## 6. WP4 — dispatch contract (commit 4)

- [x] 6.1 RED tests/test_dispatch_context_providers.py (5 failed captured) (context carries provider list + constraints, acceptance 3; optional-key backward compat)
- [x] 6.2 scripts/dispatch_context.py: providers block (fail-open at helper AND call site) + optional shape rule
- [x] 6.3 RED->GREEN captured (7/7; #527 suite 23 tests no regression)

## 7. WP5 — taint seeds + wiring (commit 5)

- [x] 7.1 RED tests/test_taint_wiring.py (10 failed captured) (taint finding -> hypothesis candidate, acceptance 5 integration; anomaly observation; EMIT registration)
- [x] 7.2 seeds yaml (21 entries/8 families) + capability doc; _INDEX.md domain row; ext-scan regen (690 lines); re_pin_references 70 files aligned
- [x] 7.3 seed_taint_candidates (mirror #669) + observe_taint (#663 D8 posture) + EMIT_ACTIONS taint_candidates + CLI --taint
- [x] 7.4 RED->GREEN captured (10/10; 85 passed across 7 suites incl. pin tests)

## 8. WP6 — deobf composition prior (commit 6)

- [x] 8.1 RED tests/test_deobf_composition.py (5 failed captured) (apkid obfuscator tag -> capability_suggestions; no fixed stage sequence exists)
- [x] 8.2 route_capability: _deobf_prior + route(ws=...) optional param (prior-only: chain/confidence untouched; backcompat ws=None)
- [x] 8.3 RED->GREEN captured (6/6; route/specialist suites 41 passed)

## 9. WP7 — gitnexus lazy index (commit 7)

- [x] 9.1 RED tests/test_gitnexus_semantic_query.py (3 failed captured: marker schema-validation gaps) (manifest registered; semantic_query resolves only when marker exists, acceptance 6)
- [x] 9.2 _valid_gitnexus_marker schema check ({source_root, indexed_at, tools}; garbage/key-less stays blocked) + aggregated blocked reasons; mcp_probe face verified unchanged (registration landed #316-era, pinned)
- [x] 9.3 RED->GREEN captured (7/7; six route/dispatch suites 70 passed)

## 10. Gate + handoff

- [x] 10.1 gates 1,3,4,5,6,7 PASS; Gate 2 final: 6 failed / 3815 passed = exactly the 6 in-ledger dev-baseline failures (gate_power_473, init_deploy_env, probe_tiers x2, v012 x2); 2 baseline pin failures FIXED by re-pin; +75 net new passing tests. Fixup commit aligns 8 first-run out-of-ledger failures (references_index x2, index_docs_contract x3, script_discipline, decide anchors x2)
- [x] 10.2 7 WP commits minted (reviewer-692-WP1..WP7, 4-5/5 PASS each) + 1 gate-alignment fixup
- [ ] 10.3 Report: branch, commits, RED/GREEN evidence, gate summary
