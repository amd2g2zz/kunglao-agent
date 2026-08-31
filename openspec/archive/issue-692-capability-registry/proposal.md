# Proposal: Android capability-provider registry (#692)

## Why

The Android path hardcodes tool order (`apkid -> mem gate -> jadx|baksmali`,
#669/#670). A human analyst does not follow a fixed pipeline — they pick the
right tool per question, given what evidence already exists and what resources
allow. User directive (2026-08-25): "不要写死一个固定流程，而是要适配当前agent。
让它更专业 更智能" + "思考当前体系怎么最优的发挥作用".

Tool research (issue body, verified against upstream READMEs):

- **dex-decompiler** (androguard org, pure Rust, https://github.com/androguard/dex-decompiler):
  DEX -> Java-like source, per-method CFG, value-flow tainting, offline
  side-effect-free bytecode emulator; PyO3 wheel `dex_decompiler`
  (`import dex_decompiler`, maturin build); CLI `dex-decompile` with
  `--only-package/--exclude/--scan-vulns/--taint-api/--taint-solve/
  --taint-method CLASS#METHOD/--emulate/--taint-output`. No JVM -> immune to
  the jadx 12GB-heap-thrash failure mode (#670's calibration point).
- **gitnexus** (https://github.com/abhigyanpatwari/GitNexus): source-code
  knowledge-graph engine, npm CLI, 16 MCP tools — semantic INDEX layer over
  decompiled source, NOT a decompiler.

## What Changes

Replaces the pipeline mental model with a **capability-provider registry**:
tools are providers that PRODUCE capabilities; `route_capability` + worker
dispatch select dynamically from workspace state.

- **WP1** `tools/_INDEX.yaml`: every Android provider entry gains
  `produces/requires/cost_hint/quality/provider` capability annotations;
  `tools/validate_index.py` gains the structural lint. New entries register
  the previously-unregistered providers: `jadx-decompile`,
  `baksmali-xref`, `apkid-prescan`, `gitnexus-query`.
- **WP2** `tools/static/dexdc_scanner.py` (new): dexdc wrapper (PyO3
  `import dex_decompiler` first, CLI `dex-decompile` fallback) emitting
  `evidence/dexdc_index.json` (gitnexus-shape wire, #670) +
  `evidence/dexdc_taint.json`; `toolchain.FIXES["dexdc"]` ToolMeta (#680
  pattern) + NextAction; landing checklist (UTF-8 guard / release-manifest /
  `tools/_index-static.md` row).
- **WP3** `scripts/route_capability.py`: new provider-selection pass —
  given a capability + workspace state (evidence files, mem-gate verdict,
  provider-health failures), rank providers by quality then cost, annotate
  preconditions. Mem-gate verdict demoted from flow-gate to a precondition
  annotation on the jadx provider. New `scripts/provider_health.py`
  (fail-open runtime failure memory).
- **WP4** `scripts/dispatch_context.py`: the dispatch context block carries
  a `providers` block (full ranked list + constraints) so the WORKER can
  switch tools in-flight; runtime failure records provider-health state
  consumed by WP3 next round (online learning, no config edit).
- **WP5** taint seeds: `references/re-library/android-fingerprint-seeds.yaml`
  (extensible fingerprint-API table, lifecycle per yara rules) +
  `android-fingerprint-apis.md` capability doc; `dexdc_taint.json` findings
  feed `hypothesis_seeder` (#662) as competitor candidates and
  `anomaly_detector` (#663) observations.
- **WP6** deobf as capability COMPOSITION (no fixed order): apkid's
  obfuscator tag raises the PRIOR that string_decrypt/dex_rewrite will be
  wanted (`route_capability` capability_suggestions), never a stage
  sequence.
- **WP7** gitnexus MCP registration face: already in `mcp_probe.MANIFEST`
  (android HARD, #316-era); this change declares the `android:semantic-query`
  capability with the lazy-index precondition — index built only when a
  claim needs it (marker `evidence/gitnexus_index.json`), never pre-run.

## Capabilities

### New Capabilities

- `android-capability-providers`: every matrix capability resolves to a
  ranked, state-aware provider list (same query, different workspace states
  -> different providers); provider failures flip preference on the next
  round; the worker dispatch context carries the full list + constraints.

### Modified Capabilities

- `tool-selection` (route_capability): gains `--capability` direct query +
  provider selection pass; existing feature/claim routing unchanged.
- `dispatch-context` (#527): gains the optional `providers` block
  (backward-compatible — `validate_context_shape` treats it as optional).
- `hypothesis-seeding` (#662): gains `seed_taint_candidates` (dexdc taint
  findings -> competitor candidates), mirroring #669's apkid wiring.
- `anomaly-observation` (#663): gains taint-findings observation input.

## Impact

- **New files**: `tools/static/dexdc_scanner.py`, `scripts/provider_health.py`,
  `references/re-library/android-fingerprint-seeds.yaml`,
  `references/re-library/android-fingerprint-apis.md`, tests (7 suites),
  this openspec change.
- **Modified files**: `tools/_INDEX.yaml`, `tools/validate_index.py`,
  `tools/_index-static.md`, `scripts/toolchain.py` (FIXES+NextAction),
  `scripts/route_capability.py`, `scripts/dispatch_context.py`,
  `scripts/hypothesis_seeder.py`, `scripts/anomaly_detector.py`,
  `scripts/event_taxonomy.py` (EMIT_ACTIONS + taint_candidates),
  `references/_INDEX.md`, `release-manifest.yaml`, `CHANGELOG.md`.
- **Backward compatibility**: _INDEX.yaml annotations are additive optional
  keys (validator checks well-formedness when present); dispatch context
  `providers` key optional; existing wire shape `smali_index.json`/
  `dexdc_index.json` share the #670 gitnexus-shape contract.
- **Out of scope** (issue): packed-APK unpacking workers, native .so layers
  (#617 flow stays), replacing jadx-ok when budget allows.
