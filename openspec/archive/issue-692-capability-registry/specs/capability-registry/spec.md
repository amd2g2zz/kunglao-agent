# Spec — Android capability-provider registry (#692)

## ADDED Requirements

### Requirement: tools/_INDEX.yaml SHALL carry capability-provider annotations, linted structurally

Provider entries MUST carry the annotation block `produces / requires /
cost_hint / quality / provider`. `tools/validate_index.py` MUST reject an
index where: a provider entry misses any annotation field; `produces` is
empty or holds non-`<domain>:<operation>` tags; `requires` holds tokens
outside the closed vocabulary (design D2); `cost_hint.mem_gb` is negative or
`cost_hint.time` is not `probe|cheap|deep`; `quality` is not a map
{produced capability: high|mid|floor} covering exactly `produces`; `capability` is not a member of `produces`; or `provider`
is duplicated across entries. Entries without `provider` are unaffected.

#### Scenario: provider entry missing quality
- **WHEN** the index holds an entry with `provider: jadx` but no `quality`
- **THEN** validate_index exits 1 naming the entry and the missing field

#### Scenario: capability outside produces
- **WHEN** an entry declares `capability: android:java-source` while
  `produces: [android:bytecode-truth]`
- **THEN** validate_index exits 1 (primary tag must be real)

#### Scenario: non-provider entries untouched
- **WHEN** an entry carries no `provider` key
- **THEN** validate_index applies only the legacy rules (no annotation error)

### Requirement: The registry SHALL cover the D0 capability x provider matrix

`android:java-source` (jadx->dexdc->baksmali), `android:call-graph`
(gitnexus->dexdc->baksmali), `android:data-flow` (dexdc sole),
`android:string-decrypt` (dexdc->smali), `android:algorithm-verify` (dexdc
sole), `android:semantic-query` (gitnexus sole), `android:dex-rewrite`
(smali/dexlib2 sole), `android:bytecode-truth` (baksmali sole) MUST each be
producible by at least one registered provider entry. jadx's precondition
MUST be the mem-budget token (the #670 gate demoted to a provider
precondition, not a pipeline stage).

#### Scenario: matrix coverage check
- **WHEN** the shipped tools/_INDEX.yaml is scanned for android: capability tags
- **THEN** every D0 capability has >= 1 provider entry and every provider
  name matches a `toolchain.FIXES` key or an `mcp_probe.MANIFEST` name

### Requirement: route_capability SHALL rank providers from workspace state

`select_providers(capability, tools, state)` MUST rank providers by quality
(high > mid > floor) then `cost_hint.mem_gb` ascending, evaluate `requires`
tokens against workspace state only, annotate each provider
`available | blocked(<reason>) | unverified(<token>)`, and recommend the
first available provider. The CLI MUST accept `--capability <tag>` for
direct queries. No live environment probe MAY run inside selection
(unresolved tokens are `unverified`, never `blocked`).

#### Scenario: budget-tight vs budget-rich (acceptance 2)
- **WHEN** evidence/apk_mem_gate.json verdict is `smali-only` and
  android:java-source is queried
- **THEN** jadx is `blocked(mem budget)` and the recommendation is dexdc
- **WHEN** the verdict is `jadx-ok` and no source tree exists
- **THEN** the recommendation is jadx

#### Scenario: source tree flips call-graph provider (acceptance 2)
- **WHEN** a decompiled source tree exists under evidence/ and
  evidence/gitnexus_index.json is present and android:call-graph is queried
- **THEN** the recommendation is gitnexus

### Requirement: Provider failures SHALL flip preference on the next round

`scripts/provider_health.py` MUST record runtime tool failures into
`<ws>/provider_health.json` (fail-open). A provider with a failure newer
than 24h MUST be demoted below all non-failed providers in
`select_providers`; expiry restores registry order.

#### Scenario: jadx times out (acceptance 4)
- **WHEN** provider_health records jadx outcome=fail and android:java-source
  is queried in a budget-rich state
- **THEN** the recommendation is dexdc (not jadx)

#### Scenario: failure expires
- **WHEN** the recorded failure is older than 24h
- **THEN** jadx is preferred again in a budget-rich state

### Requirement: The worker dispatch context SHALL carry the provider list + constraints

`build_dispatch_context` MUST include a `providers` block (the
select_providers result for the claim's capability, or an explicit one)
carrying every ranked provider with status and blocked/unverified reasons,
so the worker holds in-flight degradation authority. The key MUST remain
optional — contexts without it stay valid (backward compat with #527).

#### Scenario: context carries constraints (acceptance 3)
- **WHEN** a dispatch context is built in a budget-tight workspace
- **THEN** the providers block lists jadx with `blocked` and a reason, and
  the recommended provider with `available`

#### Scenario: old-shape context still valid
- **WHEN** a context without a providers key is validated
- **THEN** validate_context_shape passes

### Requirement: dexdc_scanner SHALL emit the two evidence schemas, fail-open

`tools/static/dexdc_scanner.py` MUST detect the PyO3 wheel
(`import dex_decompiler`) first, then the `dex-decompile` CLI; absence
writes status=`unavailable` evidence and exits 0 (fail-open, never raises).
`evidence/dexdc_index.json` MUST be gitnexus-shape ({tool, version, target,
classes[].methods[].xrefs{calls,called_by}, scanned_at} — the #670 wire).
`evidence/dexdc_taint.json` MUST carry {tool, status, target, seeds,
issues[].{rule,source,sink,traces}, count, scanned_at}. Stdout/stderr MUST
be UTF-8-guarded (#317).

#### Scenario: no wheel, no CLI
- **WHEN** neither the module nor the binary exists
- **THEN** both evidence files carry status `unavailable` and exit code is 0

#### Scenario: taint findings wire (acceptance 5)
- **WHEN** evidence/dexdc_taint.json holds an issue with source seed
  getDeviceId and the workspace has a pq-family hypothesis
- **THEN** hypothesis_seeder.seed_taint_candidates appends a
  `taint:<category>:<api>` candidate (idempotent) and emits `taint_candidates`

### Requirement: Taint seeds SHALL live as extensible reference data

`references/re-library/android-fingerprint-seeds.yaml` MUST hold
`{seeds: [{api, category, risk}]}` covering the fingerprint-API families
(device ids / SIM / sensors / MAC / clipboard / ...); it is consumable by
`dexdc_scanner --seeds` and extensible without code change (yara-rules
lifecycle). The companion capability doc MUST be pinned in
references/_INDEX.md and surfaced by the regenerated _INDEX.ext.yaml.

#### Scenario: seeds table consumed
- **WHEN** dexdc_scanner runs with the default seeds path
- **THEN** the taint evidence's `seeds` list reflects the table's api values

### Requirement: Deobfuscation SHALL be a capability composition, never a fixed stage sequence

No code path MAY encode a deobf stage order. apkid's obfuscator tag MUST
raise a PRIOR only: `route_capability` MUST emit `capability_suggestions`
listing android:string-decrypt and android:dex-rewrite when
evidence/apkid.json reports an obfuscator rule, with a rationale line naming
the rule.

#### Scenario: obfuscation prior (WP6)
- **WHEN** evidence/apkid.json summary holds obfuscator rules and route() runs
- **THEN** capability_suggestions contains android:string-decrypt and
  android:dex-rewrite and the rationale names the apkid rule

### Requirement: semantic_query SHALL resolve only when the gitnexus index exists

gitnexus stays registered per `mcp_probe.MANIFEST` (android, HARD). The
android:semantic-query selection MUST annotate gitnexus
`blocked(needs lazy index build)` while `evidence/gitnexus_index.json` is
absent, and MUST NOT itself build the index (lazy: built by the worker when
a claim needs it; marker `{source_root, indexed_at, tools}`).

#### Scenario: no index (acceptance 6)
- **WHEN** android:semantic-query is queried without the marker
- **THEN** gitnexus is blocked and recommendation is None with the lazy-build note

#### Scenario: index present (acceptance 6)
- **WHEN** the marker exists
- **THEN** gitnexus is available and recommended
