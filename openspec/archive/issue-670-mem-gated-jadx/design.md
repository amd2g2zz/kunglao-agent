# Design — memory-gated jadx dispatch (#670)

## D1. Where the gate runs (intake Phase 0, after #669 apkid)

`scripts/kunglao_init.py` android flow Phase 0 sequence (post-#669):
1. **target alignment** (#455) - apk/jar/dex.
2. **toolchain check** - presence probes for jadx + baksmali + apkid.
3. **apkid scan** (#669) - `evidence/apkid.json`.
4. **apk_mem_gate** (NEW for #670) - `evidence/apk_mem_gate.json`. Verdict selects dispatch.
5. **dispatch** - jadx-ok -> full jadx; targeted-jadx -> baksmali xref + per-class jadx; smali-only -> baksmali + smali semantic; REFUSE -> abort with structured reason.

For JAR target, the gate ALWAYS emits REFUSE — no smali fallback exists.

## D2. Memory model

```
est_heap_gb   = max(apk_mem_floor_gb, apk_mem_dex_factor * dex_bytes_total / GB)
budget_gb     = apk_mem_budget_ratio * avail_gb
avail_gb      = stdlib mem (ctypes GlobalMemoryStatusEx on Windows / sysconf on POSIX)
verdict       = f(est, budget, target_ext):
                 ext == ".jar" AND budget < est       -> REFUSE
                 ext == ".apk" AND budget >= 1.5*est  -> jadx-ok
                 ext == ".apk" AND est <= budget < 1.5*est -> targeted-jadx
                 ext == ".apk" AND budget < est       -> smali-only
```

Defaults (`apk_mem_dex_factor=50`, `apk_mem_floor_gb=4`, `apk_mem_budget_ratio=0.65`) are loaded from `analysis_state.txt` (operator-tunable, defaults baked in).

Calibration basis string travels in the JSON output per numeric-fidelity (#54): `calibration_basis: "single data point - refine with more samples"`.

## D3. Schema for `evidence/apk_mem_gate.json`

```yaml
target: "<absolute-path>"
target_ext: ".apk" | ".jar"
apk_size: int
dex_count: int
dex_bytes_total: int
est_heap_gb: float
avail_gb: float
budget_gb: float
verdict: "jadx-ok" | "targeted-jadx" | "smali-only" | "refuse"
reason: string
calibration_basis: string
evaluated_at: string
```

For JAR target: `dex_count=0`, `dex_bytes_total=<jar size>`, `est_heap_gb` is the floor (4GB), `verdict="refuse"` with `reason: "jadx-infeasible: pure Java has no smali fallback"`.

## D4. Schema for `evidence/smali_index.json` (gitnexus-compatible)

```yaml
tool: "baksmali"
version: "2.5.2"
target: "<absolute-apk-path>"
classes: [list of {name, methods: [list of {name, signature, xrefs: {called_by: [...], calls: [...]}}]}]
scanned_at: ISO8601
```

`xrefs` populated by per-class `baksmali xref` (one class at a time; full call graph is N invocations). The shape mirrors gitnexus's call-graph output so downstream consumers (anomaly detector #663, hypothesis seeder #662) don't branch on tool identity.

## D5. baksmali toolchain registration

- FIXES entry: `"baksmali": "install baksmali (apt install baksmali / brew install baksmali / jar download); verify `baksmali --version`"`
- NextAction: `NextAction("install", "<apt/brew/jar url>")`
- URL embedded inline (per user directive about tool addresses).
- T1 presence probe: `baksmali --version` returns 0.

## D6. Event.JADX_INFEASIBLE (intake-level, NOT DRAIN)

`scripts/convergence_check.py` Event enum gains:

```python
JADX_INFEASIBLE = "JADX_INFEASIBLE"   # #670 intake-level (NOT in DRAIN)
```

The event name exists for observability consistency but is NEVER raised by convergence_check itself — the REFUSE verdict aborts intake BEFORE convergence starts. Documented as such in the enum docstring.

## D7. route_capability.py triggers

Two new trigger rules:

```
target_ext == ".jar" -> refuse (always; no smali fallback)
target_ext == ".apk" AND verdict in (targeted-jadx, smali-only) ->
    select baksmali agent over jadx agent
target_ext == ".apk" AND verdict == "jadx-ok" ->
    default jadx dispatch
```

The agent dispatch contract reads `evidence/apk_mem_gate.json` to decide. REFUSE verdict aborts the dispatch loop entirely (kunglao_init.py exit code reflects REFUSE).

## D8. Fail-open layers

- apk_mem_gate binary read error (corrupt APK) -> verdict="refuse", reason carries exception message (REFUSE is safer than silent OK on a broken APK).
- baksmali binary missing -> baksmali_index.py writes empty `classes: []` + `tool: "baksmali"`, `status: "unavailable"`; downstream consumers skip on empty.
- Per-class xref failure -> that class's xrefs are `[]`; other classes unaffected.

## D9. Test strategy (RED-first)

apk_mem_gate (8 RED):
- RED1 small APK (1MB dex, 8GB avail) -> jadx-ok.
- RED2 large APK (50MB dex, 8GB avail) -> smali-only.
- RED3 medium APK (10MB dex, 8GB avail) -> targeted-jadx.
- RED4 JAR target -> refuse (regardless of budget).
- RED5 dex_bytes_total is sum of dex file sizes (not zip overhead).
- RED6 avail_gb > 0 always (falls back to 4GB on detection failure).
- RED7 calibration_basis always populated.
- RED8 evidence JSON written even on REFUSE.

baksmali_index (4 RED):
- RED1 baksmali missing -> noop + warning, no crash.
- RED2 schema shape (tool, version, classes, scanned_at).
- RED3 gitnexus-shape compat (calls + called_by arrays).
- RED4 fail-open on per-class xref failure.

## D10. Out of scope

- Semantic/NLU intent matching (anchor-substring is the mechanical floor; embedding-based coverage is a future issue if false negatives bite).
- verdict.json reconciliation (the check reads task_spec directly; wiring evidence/verdict.json into the comparison is follow-up scope).
- #634 park/idle states (loop cost — different layer).