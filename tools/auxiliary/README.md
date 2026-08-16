# tools/auxiliary — auxiliary tool home

## Tools

| File | Tool | Responsibility |
|---|---|---|
| `sanitize.py` | `sanitize-text` | prompt-injection sanitization CLI for sample-derived text (#307/#333, see below) |
| `audit_legacy_proven.py` | `audit-legacy-proven` | legacy PROVEN claim audit (BLIND signature dimension + index traceability; homed here from the tools/ root layer since #340) |
| `capture_golden.py` | `capture-golden` | golden master baseline capture (homed here since #340) |
| `measure_blind_coverage.py` | `measure-blind-coverage` | BLIND blind-verification coverage measurement (homed here since #340) |
| `measure_cold_start.py` | `measure-cold-start` | cold-start token baseline measurement (homed here since #340) |

`audit_legacy_proven.py` lazily reuses the index builder from `tools/pipelines/build_evidence_index.py` (cross-category import; it adds `tools/pipelines/` to `sys.path` itself).

### sanitize.py — sample-derived text sanitization CLI (#307 / #333)

Deterministic text sanitization, invoked before sample-derived content enters an LLM worker's context.

- `--mode zero-width|homoglyph|markers` — single injection-surface sanitization (zero-width characters / homoglyphs / instruction markers)
- `--mode ansi` — strips ANSI escape sequences (CSI/OSC/DCS/Fe) and C0 control characters (keeps `\n` `\t`, includes DEL), emitting `ansi_count`/`ctrl_count` + before/after sha256 (#333; `full` does not include this pass, keeping #307 full semantics unchanged)
- default (full) = all three injection surfaces; output contract for `--json` / `--reproduce` / `--report-only` is in the module docstring

The integration point (before a worker reads tool output into context) is tracked separately after the #310 merge — see issue #333.

## Relation to the index docs

A worker reads `tools/_index-auxiliary.md` first (the 6-segment contract entries for the auxiliary domain's 5 tools: Purpose/Usage/Inputs/Outputs/exit code/when_not, with directly copyable usage); this README only explains the in-home file division and directory history. The machine contract is `tools/_INDEX.yaml`. The category id matches the directory name (#340; the old id `aux` is a Windows reserved device name and cannot be a directory name, so the id was renamed with the directory).
