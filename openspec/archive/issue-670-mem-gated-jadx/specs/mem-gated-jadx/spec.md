## ADDED Requirements

### Requirement: apk_mem_gate SHALL produce `evidence/apk_mem_gate.json` at android Phase 0

The gate MUST run after the #669 apkid scan and BEFORE jadx dispatch in the android intake flow. It MUST always write `evidence/apk_mem_gate.json` (fail-open — operators audit the verdict even on REFUSE). The verdict selects the downstream dispatch path: `jadx-ok`, `targeted-jadx`, `smali-only`, or `refuse`.

#### Scenario: small APK, plenty of memory
- **WHEN** target is `.apk`, dex_bytes_total small, and avail_gb large
- **THEN** verdict is `jadx-ok` and `reason` is empty

#### Scenario: large APK, tight memory
- **WHEN** target is `.apk`, dex_bytes_total large, and budget < est
- **THEN** verdict is `smali-only`

#### Scenario: medium APK, marginal memory
- **WHEN** target is `.apk`, est <= budget < 1.5*est
- **THEN** verdict is `targeted-jadx`

#### Scenario: JAR target
- **WHEN** target is `.jar`
- **THEN** verdict is `refuse` with reason `"jadx-infeasible: pure Java has no smali fallback"` regardless of available memory

### Requirement: `evidence/apk_mem_gate.json` SHALL carry the memory model + calibration basis

The file MUST contain every key documented below. `calibration_basis` MUST always be populated (numeric-fidelity per #54). Defaults from `analysis_state.txt`: `apk_mem_dex_factor=50`, `apk_mem_floor_gb=4`, `apk_mem_budget_ratio=0.65`. `avail_gb` MUST be read from `ctypes.windll.kernel32.GlobalMemoryStatusEx` on Windows / `os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGESIZE")` on POSIX; falls back to 4 GB on detection failure.

```yaml
target: string
target_ext: ".apk" | ".jar"
apk_size: integer
dex_count: integer
dex_bytes_total: integer
est_heap_gb: float
avail_gb: float
budget_gb: float
verdict: "jadx-ok" | "targeted-jadx" | "smali-only" | "refuse"
reason: string
calibration_basis: string
evaluated_at: string
```

The file MUST contain every key above. `calibration_basis` MUST always be populated (numeric-fidelity per #54). Defaults from `analysis_state.txt`: `apk_mem_dex_factor=50`, `apk_mem_floor_gb=4`, `apk_mem_budget_ratio=0.65`. `avail_gb` is read from `ctypes.windll.kernel32.GlobalMemoryStatusEx` on Windows / `os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGESIZE")` on POSIX; falls back to 4 GB on detection failure.

#### Scenario: schema always populated
- **WHEN** scanner writes the file (any verdict)
- **THEN** all keys are present and `calibration_basis` is non-empty

#### Scenario: JAR target schema
- **WHEN** target is `.jar`
- **THEN** `dex_count=0`, `dex_bytes_total=<jar size>`, `est_heap_gb` is the floor (4 GB), `verdict="refuse"`

### Requirement: baksmali_index SHALL produce `evidence/smali_index.json`

When invoked at android intake Phase 0 (after apk_mem_gate, conditional on `verdict in {targeted-jadx, smali-only}`), the tool MUST emit `evidence/smali_index.json` with the gitnexus-shape: `{tool, version, target, classes: [{name, methods: [{name, signature, xrefs: {called_by: [...], calls: [...]}}]}], scanned_at}`.

#### Scenario: baksmali binary present
- **WHEN** `baksmali --version` exits 0
- **THEN** classes/methods/xrefs populated from `baksmali list --format json` + per-class `baksmali xref`

#### Scenario: baksmali binary missing
- **WHEN** `baksmali --version` returns non-zero
- **THEN** file is written with `classes: []`, `tool: "baksmali"`, and a warning is emitted to stderr; downstream consumers skip on empty classes

#### Scenario: per-class xref failure
- **WHEN** `baksmali xref <cls>` returns non-zero for one class
- **THEN** that class's `xrefs` are empty; other classes unaffected

### Requirement: baksmali SHALL be registered in toolchain

`scripts/toolchain.py` MUST register `baksmali` in FIXES dict (key: `"baksmali"`, value: install guidance with upstream URL inline) + `_STATIC_NEXT_ACTIONS` dict (key: `"baksmali"`, value: `NextAction("install", "<install command>")`).

#### Scenario: toolchain probe reports baksmali
- **WHEN** android toolchain check runs
- **THEN** the report includes a `baksmali` item with status PRESENT/MISSING + the registered NextAction

### Requirement: Event.JADX_INFEASIBLE SHALL exist as an intake-level event

`scripts/convergence_check.py` Event enum MUST gain `JADX_INFEASIBLE = "JADX_INFEASIBLE"` with a docstring note that it is intake-level (NOT in DRAIN). The event is NEVER raised by convergence_check — the REFUSE verdict aborts intake BEFORE convergence starts. The name exists for observability consistency.

#### Scenario: enum value present
- **WHEN** `scripts/convergence_check.py` is imported
- **THEN** `Event.JADX_INFEASIBLE` is accessible and its value is the string `"JADX_INFEASIBLE"`

### Requirement: route_capability.py SHALL select dispatch from apk_mem_gate verdict

When `evidence/apk_mem_gate.json` is present, the route function MUST:
- REFUSE verdict -> select no dispatch (kunglao_init exits with REFUSE indicator).
- targeted-jadx or smali-only -> prefer `baksmali_index` agent over `jadx` agent.
- jadx-ok -> default `jadx` agent dispatch.

#### Scenario: REFUSE short-circuits dispatch
- **WHEN** evidence/apk_mem_gate.json has verdict=refuse
- **THEN** route() returns no agent and exit reflects REFUSE

#### Scenario: smali-only selects baksmali agent
- **WHEN** verdict is smali-only and a baksmali-index agent is registered
- **THEN** route() prefers the baksmali-index agent

### Requirement: CLI surface

`tools/static/apk_mem_gate.py` CLI SHALL accept `<workspace> <target>` arguments, write `evidence/apk_mem_gate.json`, and exit 0 always (fail-open: even REFUSE is an expected outcome; the operator audit JSON is the contract).

#### Scenario: CLI invocation
- **WHEN** `python tools/static/apk_mem_gate.py <workspace> <target>` is run
- **THEN** `<workspace>/evidence/apk_mem_gate.json` is written and stdout carries one-line JSON `{verdict, est_heap_gb, budget_gb}` for operator audit

`tools/static/baksmali_index.py` CLI SHALL accept `<workspace> <apk>` and write `evidence/smali_index.json`, exit 0 on ok/unavailable, exit 1 on hard error.

### Requirement: Operator override (`analysis_state.txt`)

Operator MUST be able to set `apk_mem_override=jadx|baksmali|refuse` in `analysis_state.txt` to force a verdict regardless of the memory model. Default (key absent) MUST use the calculated verdict. The `calibration_basis` field MUST note when an override was applied.

Operator may set `apk_mem_override=jadx|baksmali|refuse` in `analysis_state.txt` to force a verdict regardless of the memory model. Default (key absent) is to use the calculated verdict.

#### Scenario: operator sets override=jadx
- **WHEN** `apk_mem_override=jadx` is set
- **THEN** verdict is `jadx-ok` regardless of memory math; `calibration_basis` notes the override

#### Scenario: operator sets override=refuse
- **WHEN** `apk_mem_override=refuse` is set
- **THEN** verdict is `refuse` regardless of memory math