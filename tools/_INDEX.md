# tools/ Domain Index — progressive disclosure entry point

> Orchestrator: read this file once per round, pick a category, dispatch the worker; the worker reads `_index-<category>.md` (per-tool contract entries: Purpose/Usage/Inputs/Outputs/exit code/when_not — directly copyable invocations), then loads `_INDEX.yaml` for the machine contract. Full per-category catalog below the category table.

## Category table

| Category | Index file | Tool shelf (examples) | Purpose |
|---|---|---|---|
| crypto | `_index-crypto.md` | crypto-tool | encryption/decryption/encoding/hashing tools |
| static | `_index-static.md` | die-probe, pe-analyze, yara-scan | static identification/trait-extraction tools |
| ghidra | `_index-ghidra.md` | ghidra-recon, ghidra-decompile-functions, ghidra-vtable-struct, ghidra-evidence-annotations, ghidra-scan-pointer | Ghidra disassembly/function-level analysis |
| dynamic | `_index-dynamic.md` | x64dbg-remote, frida-remote | VM dynamic debugging/runtime analysis (no local directory, MCP-provided) |
| pipelines | `_index-pipelines.md` | build-evidence-index | evidence index/report pipeline |
| auxiliary | `_index-auxiliary.md` | sanitize-text, measure-cold-start | auxiliary/miscellaneous tools |

| Scenario | Category |
|---|---|
| Fast identification of a new sample (language/compiler/packer) | static |
| Encryption/encoding/hash identification and decoding | crypto |
| Function-level disassembly / imports / xrefs / structure recovery | ghidra |
| Runtime dynamic validation (single-step/breakpoints/hooks, VM-only) | dynamic |
| Evidence registration / index building / report generation | pipelines |
| Hashing / file metadata / small chores | auxiliary |

## External capabilities (not on this toolshelf, not registered in `_INDEX.yaml`)

| Capability | Provider | Entry point |
|---|---|---|
| Frida dynamic instrumentation (hook/attach) | MCP `mcp__frida__*` + VM channel `192.168.20.128:1337` | `_index-dynamic.md`; hook templates in `templates/frida/` |
| x64dbg remote debugging | MCP `mcp__x64dbg__*` (`connect_remote` only; everything else forbidden on the host) | `_index-dynamic.md` |
| T2 emulation/simulated execution (Qiling/unicorn) | external skill `/malware-framework` | see the directory layout in [README.md](README.md) |
| plan orchestration templates (recipes) | `tools/pipelines/recipes/*.yaml` (pure-data templates, not an executor) | `tools/pipelines/README.md` |

## Per-category index files

| File | Category | Purpose | When to read |
|------|----------|---------|-------------|
| `_index-crypto.md` | crypto | crypto tool contract entries (per-tool H3 entry: Purpose/Usage/Inputs/Outputs/exit code/when_not) | when a worker is dispatched to cipher-identification/decoding/hash tasks |
| `_index-static.md` | static | static tool contract entries (same template) | when a worker is dispatched to static triage tasks |
| `_index-ghidra.md` | ghidra | ghidra tool contract entries (same template) | when a worker is dispatched to function-level disassembly tasks |
| `_index-dynamic.md` | dynamic | VM dynamic tool contract entries (MCP-provided, same template) | when a worker is dispatched to dynamic-debugging tasks |
| `_index-pipelines.md` | pipelines | pipelines tool contract entries (same template) | when a worker is dispatched to evidence-registration/report tasks |
| `_index-auxiliary.md` | auxiliary | auxiliary tool contract entries (same template) | when a worker needs small tasks like hashing/file metadata |

## Top-level tools files

| File | Category | Purpose | When to read |
|------|----------|---------|-------------|
| `_INDEX.yaml` | machine-contract | machine tool index (schema `tools-index/1`): name/category/capability/tier/cost_tier/input_output/when_not, validated by `validate_index.py` | when a machine-readable tool registry is needed / for gate calls |
| `README.md` | docs | toolshelf guide: structure rules (#340) + directory layout + contract-field meanings + MD format rules + how to register a new tool | when understanding the layout / registering / changing contract fields |
| `tool-search.py` | gate(meta) | deterministic query CLI over `_INDEX.yaml` (zero LLM/zero network; root-layer meta-tool exception, see README structure rules) | when looking up tools by capability tag/budget |
| `validate_index.py` | gate(meta) | machine-contract validator for `_INDEX.yaml` (exit 0=pass / 1=fail, gate-callable; root-layer meta-tool exception) | when validating the index or wiring it into a gate |

## tools/ scripts (placed in category directories, #340)

| File | Category | Purpose | When to read |
|------|----------|---------|-------------|
| `crypto/crypto-tool.py` | crypto | 8-algorithm encrypt/decrypt/decode CLI (chacha/xor-add/rolling-xor/lzss/lzma-raw/rsa-unpad/go-byte-transform/va-to-off) | when identifying/trial-decrypting an encryption/encoding/compression layer |
| `auxiliary/audit_legacy_proven.py` | auxiliary | audits legacy PROVEN fact states | when cleaning up old fact states |
| `pipelines/build_evidence_index.py` | pipelines | evidence index builder (evidence/_index.json + _INDEX.md) | when registering the index after evidence lands |
| `auxiliary/capture_golden.py` | auxiliary | golden case capture | when updating golden fixtures |
| `static/disasm_constant_check.py` | static | byte-exact disassembly constant validation | when validating disassembly assertions |
| `auxiliary/measure_blind_coverage.py` | auxiliary | blind-verification coverage measurement | when evaluating blind-verification coverage |
| `auxiliary/measure_cold_start.py` | auxiliary | cold-start measurement | when evaluating cold-start cost |
| `auxiliary/sanitize.py` | auxiliary | prompt-injection sanitization of sample content (zero-width/homoglyph/instruction markers) | before feeding sample-derived text to an LLM worker |
| `ghidra/run_ghidra_postscript.py` | ghidra | analyzeHeadless wrapper (invokes the 5 postScript tools) | when the Ghidra tools must run headless |
| `_lib/lib_disasm.py` | shared-lib | cross-category shared library: PE/capstone VA→offset core (not registered in the index) | when a new disassembly tool reuses VA→offset |
