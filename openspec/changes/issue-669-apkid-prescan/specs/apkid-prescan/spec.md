## ADDED Requirements

### Requirement: apkid pre-scan SHALL produce `evidence/apkid.json` at android Phase 0

When `scripts/kunglao_init.py` runs the android flow, AFTER target alignment + toolchain check and BEFORE jadx dispatch, it SHALL invoke `scripts/apkid_scanner.py` to scan the resolved APK. The scanner MUST ALWAYS write `evidence/apkid.json` regardless of whether the `apkid` binary is installed (fail-open). The output is a triage signal consumed by hypothesis_seeder (#662) and downstream orchestrator consumers; it is NOT a verdict.

#### Scenario: apkid binary present, APK valid
- **WHEN** `apkid --version` exits 0 and the resolved target is a `.apk` file
- **THEN** scanner invokes `apkid scan --json <apk>`, parses the JSON output, and writes `evidence/apkid.json` with `status: ok`, `findings: [...]`, `summary: {packer, compiler, obfuscator, anti_vm, anti_debug, total}`

#### Scenario: apkid binary missing
- **WHEN** `apkid --version` returns non-zero or `FileNotFoundError`
- **THEN** scanner writes `evidence/apkid.json` with `status: unavailable`, `reason: "<apkid discovery error>"`, empty `findings` and `summary`. Scanner exits 0; intake continues.

#### Scenario: input is not an APK
- **WHEN** the resolved target does not end in `.apk` (case-insensitive)
- **THEN** scanner writes `evidence/apkid.json` with `status: error`, `reason: "target is not an APK"`. Scanner exits 1 (still no crash; downstream sees the error state).

### Requirement: `evidence/apkid.json` SHALL carry the schema below

The file MUST contain every required top-level key, and the `summary` object MUST always expose all six sub-keys (defaults `[]` / `0`). A missing summary key is a schema violation.

```yaml
tool: "apkid"
version: string
target: string
scanned_at: string
findings: list
summary:
  packer: list[string]
  compiler: list[string]
  obfuscator: list[string]
  anti_vm: list[string]
  anti_debug: list[string]
  total: integer
status: string
reason: string
```

#### Scenario: schema always populated
- **WHEN** scanner writes the file
- **THEN** all top-level keys are present; `summary` keys (`packer`, `compiler`, `obfuscator`, `anti_vm`, `anti_debug`, `total`) are ALWAYS present (defaults `[]` / `0`). Missing summary keys = schema violation.

#### Scenario: findings roll up into summary
- **WHEN** apkid returns N findings
- **THEN** `summary.packer`, `summary.compiler`, `summary.obfuscator`, `summary.anti_vm`, `summary.anti_debug` contain the distinct rule names per category, and `summary.total == len(findings)`. Empty findings -> empty lists, total 0.

### Requirement: apkid SHALL be registered in toolchain (#408 integration)

`scripts/toolchain.py` MUST register `apkid` in:
- `FIXES` dict (key: `"apkid"`, value: the human-readable install guidance).
- `_STATIC_NEXT_ACTIONS` dict (key: `"apkid"`, value: `NextAction("install", "pip install apkid")`).

`scripts/toolchain_install.py` MUST add the `apkid` install plan (pip package).

#### Scenario: toolchain probe reports apkid
- **WHEN** `scripts/toolchain.py` runs the android toolchain check
- **THEN** the report includes an `apkid` item with status `PRESENT` (binary found) or `MISSING` (binary absent), each carrying the registered `NextAction`.

### Requirement: apkid output SHALL feed the hypothesis seeder (#662 integration)

When `evidence/apkid.json` exists with `status: ok`, `scripts/hypothesis_seeder.py` SHALL append apkid-derived candidates to the matching `competitor_group` of any PQ whose id or question text contains tokens `packer`, `compiler`, `obfuscator`, `anti-debug`, or `anti-vm`. The body marker is `apkid:<category>:<rule>` (e.g., `apkid:packer:Bangcle`).

#### Scenario: APK flagged with Bangcle
- **WHEN** `evidence/apkid.json` lists `summary.packer: ["Bangcle"]` and a PQ id is `Q-packer-family`
- **THEN** the seeded hypothesis for `Q-packer-family` carries a `competitor_group` entry with body `apkid:packer:Bangcle`

#### Scenario: apkid output absent
- **WHEN** `evidence/apkid.json` does not exist or `status: unavailable`
- **THEN** hypothesis_seeder's pq-family scaffolds are unchanged; the seeder does not raise.

### Requirement: CLI surface

`scripts/apkid_scanner.py` CLI SHALL accept `<workspace> <apk-path>` arguments, write `evidence/apkid.json`, and exit:
- `0` on `status: ok` or `status: unavailable` (intake continues either way)
- `1` on `status: error` (operator-visible failure; intake still proceeds per fail-open)

#### Scenario: CLI invocation
- **WHEN** `python scripts/apkid_scanner.py <workspace> <apk>` is run
- **THEN** `<workspace>/evidence/apkid.json` is written and stdout carries a one-line JSON summary `{status, summary}` for operator audit.