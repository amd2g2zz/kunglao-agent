# tools/ghidra — Ghidra automation tool home

Holds Ghidra-related automation: the analyzeHeadless wrapper (`run_ghidra_postscript.py`) and 5
parameterized postScript tools (issue #293 absorption, sa-ghidra final). Scripts are always `--key=value`
parameterized and emit UTF-8 JSON (with `schema` / `program` / `image_base`); `--out` takes an absolute
path and mkdirs itself. `GhidraJsonScript.java` is the shared base class (`getArg` / `unescape` / JSON writer).

## Invocation entry point

```bash
python tools/ghidra/run_ghidra_postscript.py \
  --tool ghidra-recon --binary <abs-sample> --out <abs-output.json> \
  [--key value ...]   # remaining --key=value pairs are forwarded verbatim to the postScript
```

- `GHIDRA_HOME` resolution order: `--ghidra-home` → environment variable → `analysis_state.txt`
  (the `ghidra_home=...` line); missing or `analyzeHeadless.bat` absent → exit 2 with guidance.
- The temporary Ghidra project directory is deleted after use (`--keep-project` retains it).

## postScript tools (5)

| Tool id | Java source | Contract (input → output) |
|---|---|---|
| `ghidra-recon` | `GhidraRecon.java` | sample + `--search-terms/--expected-exports/--sha256/--sha1` → JSON (imports/exports/functions/strings_of_interest/suspicious_api_calls/focus_functions/go/findings) |
| `ghidra-decompile-functions` | `DecompileFunctions.java` | sample + `--addresses/--strings/--window` → JSON (per-target decompiled C + disasm window + string xrefs) |
| `ghidra-vtable-struct` | `GhidraExportVtableStruct.java` | sample + `--address/--name/--class/--apply` → JSON (vtable slot table + function fields) |
| `ghidra-evidence-annotations` | `GhidraEvidenceAnnotations.java` | sample + `--mode apply\|verify + --tsv` → JSON (annotation apply/validation summary; a verify failure raises, fail-closed) |
| `ghidra-scan-pointer` | `GhidraScanPointer.java` | sample + `--mode xref\|window` (xref: `--addresses/--bytes`; window: `--center/--window`) → JSON (xref/raw 8-byte pointer scan hits) |

The base class for all tools is `GhidraJsonScript.java` (abstract; never run as a postScript).

## Relation to the index docs

A worker reads `tools/_index-ghidra.md` first (the 6-segment contract entries for the 5 tools: Purpose/Usage/Inputs/Outputs/exit code/when_not, with directly copyable `run_ghidra_postscript.py` usage); this README only explains the in-home file division and the runtime environment. The machine contract is `tools/_INDEX.yaml`.

## exit codes (unified by run_ghidra_postscript.py)

- 0: postScript succeeded; output JSON persisted (`--out` or stdout).
- 2: error — `GHIDRA_HOME` missing / `analyzeHeadless.bat` absent / bad arguments / postScript failure (a `ghidra-evidence-annotations --mode verify` failure is fail-closed and also 2), all with error guidance.
