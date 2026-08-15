# auxiliary domain index (tool layer)

> Domain: auxiliary/miscellaneous tools (hashing, encoding, file metadata, operational measurement). When a worker is dispatched to small auxiliary tasks, read this file first, then load on demand. Contract field meanings are in [README.md](README.md); the machine contract is [_INDEX.yaml](_INDEX.yaml). The category id matches the directory name (`tools/auxiliary/`, #340); history: the old id was `aux`, but `aux` is a Windows reserved device name and cannot be a directory name, so #340 renamed the id with the directory.

## Tool catalog

| Tool | Purpose (one-liner) | When to read / when not |
|---|---|---|
| `audit-legacy-proven` | Legacy PROVEN claim audit (BLIND signature dimension + index traceability) | Read when cleaning up old PROVEN claim states; not when no legacy PROVEN needs auditing |
| `capture-golden` | Golden case capture (synthetic workspaces + CLI arguments) | Read when a contract change requires re-capturing golden baselines; not for routine analysis |
| `measure-blind-coverage` | BLIND blind-verification coverage measurement | Read when evaluating blind-verification coverage; not otherwise |
| `measure-cold-start` | Cold-start token baseline measurement | Read when measuring the cold-start token baseline; not for non-baseline measurement |
| `sanitize-text` | Prompt-injection sanitization of sample-derived text (zero-width/homoglyph/instruction markers) | Read before feeding sample-derived text to an LLM worker; not when the text is not consumed by an LLM |

## Contract entries

### audit-legacy-proven

- **Purpose**: Audit a workspace's legacy PROVEN claims (BLIND signature dimension + index traceability).
- **Usage**:
  ```bash
  python tools/auxiliary/audit_legacy_proven.py <workspace> --json
  ```
- **Inputs**: Workspace root (positional, required; reads claim-register.yaml + facts/_INDEX.md); optional `--output/--out` (persist JSON)/`--json` (stdout JSON).
- **Outputs**: Legacy PROVEN claim audit JSON/summary (default output audit-<ws>-<ts>.json).
- **exit code**: 0 success / 2 error (workspace does not exist).
- **when_not**: Not needed when no legacy PROVEN claims require audit cleanup.

### capture-golden

- **Purpose**: Re-capture golden master baselines per the CASES list (synthetic workspaces + CLI arguments).
- **Usage**:
  ```bash
  python tools/auxiliary/capture_golden.py --refresh
  ```
- **Inputs**: The CASES list (synthetic workspaces + CLI arguments in-script); optional `--out <DIR>` (default tests/fixtures/golden).
- **Outputs**: tests/fixtures/golden/{manifest.yaml, F-NN/expected/stdout.txt}.
- **exit code**: 0 success / 2 error (argument error, argparse).
- **when_not**: `--refresh` re-capture is only for contract-change flows; not for routine analysis.

### measure-blind-coverage

- **Purpose**: Measure the BLIND blind-verification coverage of PROVEN claims.
- **Usage**:
  ```bash
  python tools/auxiliary/measure_blind_coverage.py <workspace> --json
  ```
- **Inputs**: Workspace root (positional, required; reads claim-register.yaml + verifier_sign_off from facts/*.md); optional `--out`/`--reliability`.
- **Outputs**: BLIND coverage JSON (PROVEN/blind_signed/unverified/coverage).
- **exit code**: 0 done / 2 error (argument error, argparse).
- **when_not**: Not needed when blind-verification coverage is not being evaluated.

### measure-cold-start

- **Purpose**: Per-file token estimation over the workspace state-file inventory; emits the cold-start baseline.
- **Usage**:
  ```bash
  python tools/auxiliary/measure_cold_start.py <workspace> --out <out.json>
  ```
- **Inputs**: Workspace root (positional, required; reads claim-register.yaml/_INDEX/ledger/progress and other state files); optional `--rounds`.
- **Outputs**: docs/baselines/cold-start-tokens.json (per-file token estimates, default path).
- **exit code**: 0 success / 2 error (missing workspace).
- **when_not**: Not for non-cold-start-baseline measurement.

### sanitize-text

- **Purpose**: Prompt-injection sanitization of sample-derived text: zero-width character/homoglyph/instruction-marker detection and removal (the mandatory gate before feeding an LLM worker).
- **Usage**:
  ```bash
  python tools/auxiliary/sanitize.py --in <sample-derived-text> --mode full --json
  ```
- **Inputs**: Sample-derived text (`--in` or stdin) + `--mode zero-width|homoglyph|markers|full`; optional `--report-only`/`--sentinel-prefix`.
- **Outputs**: Sanitized text or JSON (zwx_count/homoglyph_count/marker_count/suspicious/sha256) + `--reproduce` field=value lines.
- **exit code**: 0 positive finding (injection detected) / 1 negative finding (nothing detected) / 2 error.
- **when_not**: Not needed when the text is not consumed by an LLM worker.
