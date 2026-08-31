# Design — Android capability-provider registry (#692)

## D0. The capability x provider matrix (THE contract)

Capabilities use the `<domain>:<operation>` grammar already enforced by
`tools/validate_index.py`; the domain is `android`.

| capability | providers (quality-high -> fallback) | precondition |
|---|---|---|
| android:java-source | jadx (high) -> dexdc (mid) -> baksmali (floor) | jadx: mem-budget verdict (#670 gate becomes a PROVIDER precondition, not a pipeline stage); dexdc: PyO3 wheel `dex_decompiler`; baksmali: baksmali jar |
| android:call-graph | gitnexus (high) -> dexdc CFG (mid) -> baksmali xref (floor) | gitnexus: indexed source tree; dexdc: dex; baksmali: dex |
| android:data-flow | dexdc taint (sole) | dex + fingerprint seed table |
| android:string-decrypt | dexdc emulator (sole) -> smali manual (floor) | dex + ciphertext |
| android:algorithm-verify | dexdc emulator (sole) | method signature + params — the maker-checker reproduce command |
| android:semantic-query | gitnexus 16 MCP tools + RAG (sole) | indexed source tree (lazily built, marker `evidence/gitnexus_index.json`) |
| android:dex-rewrite | dexlib2/smali reassembly (sole, writable) | smali toolchain — rename/patch/repackage (the only persistent form) |
| android:bytecode-truth | baksmali (sole 1:1) | dex — fact anchors, mechanical verify |

Anything not in this matrix is out of scope (packed-APK unpacking, native .so).

## D1. Registry home + entry annotations (WP1)

The registry IS `tools/_INDEX.yaml` (the execution registry every consumer
already reads; no parallel file to drift). Multi-provider = multiple entries
sharing capability tags. New OPTIONAL per-entry keys, structurally linted by
`tools/validate_index.py`:

```yaml
produces: [android:java-source, android:call-graph]  # list of domain:op tags; superset of `capability`
requires: [dex, dexdc_wheel]   # precondition tokens (closed vocab, D2)
cost_hint: {mem_gb: 1.0, time: deep}   # mem numeric GB, time: probe|cheap|deep
quality: {android:java-source: high}   # per-capability map (a provider can be
                                       # floor for one capability and high for
                                       # another); keys == the produces set
provider: jadx                 # provider identity (matches toolchain FIXES key / mcp manifest name)
```

Lint rules (apply only when `provider` is present — the annotation block is
opt-in; existing entries without a provider stay untouched):

1. `provider` present => `produces`, `requires`, `cost_hint`, `quality` all
   present and well-formed (produces = non-empty list of `<domain>:<op>`
   tags; requires = list of known tokens; cost_hint = numeric mem_gb >= 0
   plus known time tier; quality = non-empty map {produced-capability: tier},
keys exactly the produces set).
2. `capability` must be a member of `produces` (the primary tag is real).
3. Names unique (existing rule); `provider` unique across entries — one
   entry per provider, so the provider list IS the entry set.

New entries (WP1/WP2/WP7): `jadx-decompile` (static; no repo wrapper file —
execution face is worker dispatch of the external CLI, mem-gated by
`tools/static/apk_mem_gate.py`; validate_index does not enforce file
existence), `baksmali-xref` (wraps `tools/static/baksmali_index.py`),
`apkid-prescan` (wraps `scripts/apkid_scanner.py`), `gitnexus-query`
(category `static` — the `dynamic` category is documented VM-only + tier T3
per tools/README.md, which a host-side source-graph query violates; MCP
server per `mcp_probe.MANIFEST`), `dexdc-decompile` (WP2, wraps
`tools/static/dexdc_scanner.py`).

## D2. Precondition tokens (closed vocabulary)

`requires` tokens are evaluated by `route_capability` against WORKSPACE
STATE (files under the workspace) — never live environment probes (that is
toolchain's domain; a token without a workspace-state answer annotates
`unverified: <token>`, it never blocks):

| token | workspace-state answer | blocks? |
|---|---|---|
| `dex` | target shape (APK/DEX given) | only when target known non-dex |
| `mem_budget_ok` | `evidence/apk_mem_gate.json` verdict in {jadx-ok, targeted-jadx} | yes when verdict in {smali-only, refuse} |
| `dexdc_wheel` | `evidence/tool-probes.json` probe pass | unverified otherwise |
| `jadx_bin` | same probe file face | unverified otherwise |
| `smali_toolchain` | same probe file face | unverified otherwise |
| `source_tree` | decompiled source dir present under `evidence/` | yes when absent and queried |
| `gitnexus_index` | `evidence/gitnexus_index.json` marker | yes when absent (lazy build on demand) |

`mem_budget_ok` is the #670 gate DEMOTED to a provider precondition: the
mem-gate evidence still gates jadx, but as an annotation on the jadx
provider row ("blocked: mem budget") instead of a pipeline stage.

## D3. Selection pass (WP3) — `route_capability.select_providers`

```
select_providers(capability, tools, state) ->
  {
    capability,
    providers: [   # ranked: quality desc (high>mid>floor), then cost_hint.mem_gb asc, then registry order
      {name, provider, quality, cost, status: available|blocked|unverified, blocked_reason|unverified_reason}
      ...
    ],
    recommendation: <first available provider name or None>,
    rationale: [...]
  }
```

- Ranking is quality -> cost (issue: "rank providers by quality then cost").
- A provider-health FAILURE (D4) demotes that provider below all
  non-failed ones for the failure window (24h) — the failure-memory flip.
- Same capability query in two states yields different recommendations
  (acceptance 2): budget-tight => dexdc; budget-rich + no source => jadx;
  source tree present => gitnexus wins android:call-graph.
- Output rides the existing `route()` result as `providers` (additive) and
  a new `--capability <tag>` CLI mode for direct queries.

## D4. Provider health (WP4) — fail-open runtime memory

`scripts/provider_health.py`: record/query `<ws>/provider_health.json`
(`{provider: [{outcome: fail|ok, reason, ts}]}`). Written by the worker
runtime on tool failure (CLI: `record <ws> --provider jadx --outcome fail
--reason "timeout"`); read by `select_providers` (D3). Online learning with
NO config edit: failures live in the workspace, not the registry.
Fail-open: missing/corrupt file = no memory.

## D5. Dispatch context providers block (WP4)

`build_dispatch_context` gains an OPTIONAL `providers` key (fail-open): the
`select_providers` result for the claim's validated capability (or an
explicit capability argument). The block carries ALL ranked providers with
statuses + constraints, so the WORKER holds degradation authority — e.g.
jadx times out -> switch to dexdc immediately, no orchestrator round-trip
(the emit face for the switch is the existing `capability_switch` action).
`validate_context_shape` keeps its required-key set unchanged (providers
optional => old contexts stay valid; when present it must be a dict with
capability/providers keys).

## D6. dexdc wrapper (WP2) — `tools/static/dexdc_scanner.py`

Detection order (both faces fail-open to a status field, never crash):
1. PyO3: `import dex_decompiler` (the official wheel; maturin build:
   `cd dex-decompiler-py && maturin build --release && pip install
   target/wheels/dex_decompiler-*.whl`).
2. CLI fallback: `dex-decompile` binary on PATH.

Modes: `--mode index` (classes/methods/xrefs from the per-method CFG ->
`evidence/dexdc_index.json`), `--mode taint` (seeded by the fingerprint
seed table via the upstream `--taint-api` face + `--taint-solve` ->
`evidence/dexdc_taint.json`), `--mode both` (default). `--only-package`
passthrough.

Wire shapes (#670 "system optimum" contract — downstream consumers never
branch on tool identity):

- `dexdc_index.json` — gitnexus-shape: `{tool: "dexdc", version, target,
  classes: [{name, methods: [{name, xrefs: {calls, called_by}}]}],
  scanned_at}` (same face as `evidence/smali_index.json`).
- `dexdc_taint.json` — upstream IssueReport face: `{tool: "dexdc", status,
  target, seeds, issues: [{rule, source, sink, traces}], count,
  scanned_at}` (traces preserved verbatim from `--taint-output`; findings
  are the WP5 wire).

UTF-8 stdout guard (#317) at module top, same as every tools/static CLI.

## D7. Taint seeds + hypothesis/anomaly wiring (WP5)

- `references/re-library/android-fingerprint-seeds.yaml` — extensible
  machine table (lifecycle = yara rules: versioned data consumed by a
  tool, extensible without code change): `{seeds: [{api, category, risk}]}`
  over getDeviceId/getAndroidId/getSubscriberId/getSimSerialNumber/
  sensors/MAC/clipboard/... with `api` in dexdc's `--taint-api` argument
  shape.
- `android-fingerprint-apis.md` — the re-library capability doc (ext-scan
  regenerates `_INDEX.ext.yaml`; both pinned in `references/_INDEX.md`).
- `hypothesis_seeder.seed_taint_candidates(ws)` — reads
  `evidence/dexdc_taint.json`, appends `taint:<category>:<api>` candidates
  to pq-family scaffolds (exact mirror of `seed_apkid_candidates` #669:
  idempotent, fail-open, emits `taint_candidates`).
- `anomaly_detector.observe_taint(ws)` — taint findings as observations:
  scores seed-category concentration; above threshold writes
  `notes/taint-observation.md` (observation, NOT verdict — #663 D8 posture).

## D8. Deobf composition (WP6) — no fixed order

The agent composes string_decrypt (emulator) + dex_rewrite (dexlib2 rename,
the only persistent form) + re-decompile + re-index per claim, in whatever
order the claim needs. apkid's obfuscator tag merely raises the PRIOR:
`route_capability` gains `capability_suggestions` — when
`evidence/apkid.json` reports an obfuscator, android:string-decrypt and
android:dex-rewrite are listed as wanted-prior capabilities (rationale line
names the apkid rule). No deobf stage sequence exists anywhere.

## D9. gitnexus lazy index (WP7)

gitnexus is already registered (`mcp_probe.MANIFEST`, android HARD,
`claude mcp add gitnexus -- gitnexus mcp`). This change adds: the
`android:semantic-query` capability declaration (the `gitnexus-query`
_INDEX.yaml entry) and the LAZY-INDEX contract — the index is built only
when a claim needs it; the selection pass NEVER triggers a build, it only
annotates `gitnexus: blocked (needs lazy index build)` until the marker
`evidence/gitnexus_index.json` (written by the worker after building:
`{source_root, indexed_at, tools}`) exists. Cost stays tied to demand.

## D10. Test matrix (acceptance 1-7)

| # | acceptance | test |
|---|---|---|
| 1 | annotations + lint | test_index_capability_annotations (validate_index on synthetic + shipped index) |
| 2 | two states -> different providers | test_route_capability_providers (budget-tight -> dexdc; budget-rich no-source -> jadx; source present -> gitnexus) |
| 3 | dispatch context carries providers | test_dispatch_context_providers (contract) |
| 4 | failure flips preference | test_route_capability_providers (provider-health jadx fail -> dexdc first next round) |
| 5 | dexdc schemas + taint -> hypothesis | test_dexdc_scanner + test_taint_wiring (integration mirroring #669) |
| 6 | gitnexus registered; semantic_query index-gated | test_gitnexus_semantic_query |
| 7 | landing checklist | structural asserts inside the WP2/WP5 suites (manifest declared, README cataloged, UTF-8 guard source check, EMIT_ACTIONS registered, references/_INDEX pinned) |

All tests inject state via tmp workspaces / synthetic index files — no
absolute-path literals, no network, no real dexdc/jadx execution (the
wrapper's subprocess face is faked per the repo's fail-open pattern).
