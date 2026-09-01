# ghidra domain index (tool layer)

> Domain: Ghidra disassembly / function-level analysis. When a worker is dispatched to function disassembly, import/xref export, or structure-recovery tasks, read this file first, then load on demand. Contract field meanings are in [README.md](README.md); the machine contract is [_INDEX.yaml](_INDEX.yaml). The 5 postscript tools are invoked uniformly via `tools/ghidra/run_ghidra_postscript.py` (an analyzeHeadless wrapper; `--key=value` is forwarded to the postScript); async submit/poll/fetch over that wrapper goes through `tools/ghidra/ghidra_job.py` (+ `job_store.py`, the dir-backed job lib). `ghidra_diff` is its own CLI and drives the same async protocol.

## Tool catalog

| Tool | Purpose (one-liner) | When to read / when not |
|---|---|---|
| `ghidra-recon` | Function-level static reconnaissance (imports/exports/strings/suspicious APIs/Go traits) | Read when function-level static reconnaissance is needed; for single-function disassembly use ghidra-decompile-functions |
| `ghidra-decompile-functions` | Targeted decompile + disassembly window + string xrefs (optional --context adds context) | Read when targeted disassembly+decompilation is needed; bulk whole-binary disassembly is not this tool's job |
| `ghidra-vtable-struct` | vtable/callback-table structure recovery | Read when recovering a vtable/callback table structure; not without a clear vtable address or for text-only tasks |
| `ghidra-evidence-annotations` | TSV evidence annotation write-back/validation (fail-closed) | Read when writing evidence TSV back to / validating a Ghidra project; not without an evidence TSV |
| `ghidra-scan-pointer` | xref lookup / 8-byte pointer scan into a range | Read when checking address references or scanning pointers; for string location use ghidra-decompile-functions |
| `ghidra_diff` | Function-level binary diff over Ghidra Version Tracking (#308, bindiff.v1 artifact) | Read when two samples/variants need added/changed/removed function diffing; not for fresh single-sample recon |

## Contract entries

### ghidra-recon

- **Purpose**: Function-level static reconnaissance: imports/exports/strings/suspicious API calls/focus functions/Go traits packaged as JSON.
- **Usage**:
  ```bash
  python tools/ghidra/run_ghidra_postscript.py --tool ghidra-recon --binary <abs-sample> --out <abs-output.json>
  ```
- **Inputs**: Sample + `--search-terms`/`--expected-exports`/`--sha256`/`--sha1` (forwarded via `--key=value`).
- **Outputs**: JSON (meta/imports/exports/functions/strings_of_interest/suspicious_api_calls/focus_functions/go/findings).
- **exit code**: 0 success / 2 error (missing GHIDRA_HOME / analyzeHeadless.bat absent / bad arguments / postScript failure, with guidance).
- **when_not**: Not for single-function disassembly — use ghidra-decompile-functions.

### ghidra-decompile-functions

- **Purpose**: Targeted decompilation: per-target decompiled C + disassembly window + string xrefs; `--context` adds caller/callee snippets + xref strings + recovered names (ghidra_context.v1).
- **Usage**:
  ```bash
  python tools/ghidra/run_ghidra_postscript.py --tool ghidra-decompile-functions --binary <abs-sample> --out <abs-output.json> --addresses 0x401000,0x402000
  ```
- **Inputs**: Sample + `--addresses`/`--strings`/`--window`/`--context`.
- **Outputs**: JSON (per-target decompiled C + disasm window + string xrefs; `--context` adds caller/callee ~10-line snippets + xref strings + recovered names).
- **exit code**: 0 success / 2 error (missing GHIDRA_HOME / bad arguments / postScript failure).
- **when_not**: Not for bulk whole-binary disassembly; for vtable recovery use ghidra-vtable-struct.

### ghidra-vtable-struct

- **Purpose**: Recover the slot table and function fields from a vtable address; optionally persist structures/labels.
- **Usage**:
  ```bash
  python tools/ghidra/run_ghidra_postscript.py --tool ghidra-vtable-struct --binary <abs-sample> --out <abs-output.json> --address 0x140001000
  ```
- **Inputs**: Sample + `--address`/`--name`/`--class`/`--apply`.
- **Outputs**: JSON (vtable slot table + function fields; optionally persists structures/labels).
- **exit code**: 0 success / 2 error (missing GHIDRA_HOME / bad arguments / postScript failure).
- **when_not**: Not without a clear vtable address or for text-only tasks.

### ghidra-evidence-annotations

- **Purpose**: Apply/validate TSV evidence annotations back into a Ghidra project; a verify failure raises, fail-closed.
- **Usage**:
  ```bash
  python tools/ghidra/run_ghidra_postscript.py --tool ghidra-evidence-annotations --binary <abs-sample> --out <abs-output.json> --mode apply --tsv <evidence.tsv>
  ```
- **Inputs**: Sample + `--mode apply|verify` + `--tsv <path>`.
- **Outputs**: JSON (annotation apply/validation summary).
- **exit code**: 0 success / 2 error (missing GHIDRA_HOME / bad arguments / verify failure, fail-closed).
- **when_not**: Not without an evidence TSV to write back/validate.

### ghidra-scan-pointer

- **Purpose**: xref lookup, or scan for all raw 8-byte pointers into a range.
- **Usage**:
  ```bash
  python tools/ghidra/run_ghidra_postscript.py --tool ghidra-scan-pointer --binary <abs-sample> --out <abs-output.json> --mode xref --addresses 0x401000
  ```
- **Inputs**: Sample + `--mode xref|window` (xref: `--addresses`/`--bytes`; window: `--center`/`--window`).
- **Outputs**: JSON (xref / raw 8-byte pointer scan hits).
- **exit code**: 0 success / 2 error (missing GHIDRA_HOME / bad arguments / postScript failure).
- **when_not**: Not for string location only — use ghidra-decompile-functions.

### ghidra_diff

- **Purpose**: Function-level binary diff over Ghidra Version Tracking (#308): two samples into one project, GhidraBindiff.java emits a bindiff.v1 artifact; query subcommands slice it (no Ghidra needed for queries).
- **Usage**:
  ```bash
  python tools/ghidra/ghidra_diff.py create --base <base-sample> --target <target-sample> --out <artifact.json>
  ```
- **Inputs**: Two binaries (`--base`/`--target`) + subcommand (`create|status|cancel|delete|diff-summary|diff-list-functions|diff-function <addr>`); optional `--timeout`/`--ghidra-home`/`--keep-project`; queries take `--artifact` or `--job <id>` and `--side base|target`.
- **Outputs**: `bindiff.v1` JSON artifact (match statistics; identical/changed/added/removed function lists; per-function callee-change + bodyBytesChanged lenses — bodyBytesChanged is always present for matched functions).
- **exit code**: 0 success / 1 negative finding (e.g. diff-function address not in the diff) / 2 error (bad args / missing or invalid artifact / postScript failure); structured error JSON on stderr, never a traceback.
- **when_not**: Not for fresh single-sample recon (use ghidra-recon); not when an external BinDiff/Diaphora export already covers the pair.
