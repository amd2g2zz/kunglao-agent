---
name: go-symbols
description: "Stage 3.9 Go symbol recovery via unstrip (Go samples only, die.json language=Go). Runs unstrip --info / default / --format ghidra / --xref / --data-at, parses output, and WRITES evidence/unstrip-info.json + unstrip-symbols.json + unstrip-ghidra-apply.py + unstrip-ghidra-hints.json. The hints file carries prioritized_targets + itab_dispatch + struct_types + xref_map + garble_assist + annotations[] (the persistent mark-up plan ghidra-light applies to the Ghidra project). Heuristic not hardcoded - you classify functions, pick --data-at targets, and craft actionable annotations. Pure local. You DO have the Write tool - write the files yourself, do not return YAML to the caller."
# issue #310 mechanical trigger table — parsed by scripts/route_capability.py.
# Go symbol recovery precedes decompile: pipeline_order 1 wins over
# ghidra-light (4) for Go samples.
triggers:
  pipeline_order: 1
  intent:
    must_any:
      - 'go symbol'
      - 'go-symbol'
      - 'golang'
      - 'go binary'
      - 'go-binary'
      - 'go sample'
      - 'pclntab'
      - 'unstrip'
      - '符号恢复'
    exclude:
      - 'rust'
      - '\.net'
      - 'c#'
  features:
    language:
      any_of:
        - 'Go'
    import_hints:
      any_contains:
        - 'go.buildinfo'
allowedTools:
  - Read
  - Grep
  - Bash
  - Write
  - mcp__sequential-thinking__sequentialthinking
disallowedTools:
  - WebFetch
  - WebSearch
  - Edit
  - NotebookEdit
isolation: none
---

# go-symbols (Stage 3.9)

Recover Go symbols/types/itabs from pclntab via unstrip (no decompile) -> emit a Ghidra apply script **plus** a decision-and-annotation plan that ghidra-light persists onto the program.

## Inputs (passed by caller)
- `binary_path`: local Go binary
- `evidence_dir`: mal-recon/<sha1>/evidence/
- `die_path`: evidence/die.json (confirm language=Go; else STOP with degraded note)
- prior evidence for `--data-at` targets: `evidence/floss-filtered.json` (IOC/config string addrs), `evidence/cti-correlated.json`
- `unstrip_bin`: no hardcoded default — `unstrip` on PATH, else the path recorded in workspace `analysis_state.txt` (toolchain baseline) or passed by the caller

## Pipeline
1. **sequentialthinking preamble**: confirm Go; choose suspicious-name patterns; pick data addrs to probe with `--data-at`.
2. `unstrip <path> --info` -> parse -> write `unstrip-info.json` `{go_version, container, pclntab:{addr,size}, function_count, garble:{heuristic,reasons[]}, module_deps[]}`.
3. `unstrip <path>` -> parse listing -> write `unstrip-symbols.json`: Layer A `{total_funcs, with_signature, methods, types, itabs}`; Layer B `suspicious_functions[]` (classify by name into `decrypt|c2|loader|persistence|exfil|recon`), `types_sample[]`, `itabs_sample[]`.
4. `unstrip <path> --format ghidra` -> write `unstrip-ghidra-apply.py` **VERBATIM** (do not modify).
5. top-K suspicious funcs: `unstrip <path> --xref <name>` (collect callers incl. indirect dispatch); flagged data addrs: `unstrip <path> --data-at <addr>` (interpret via type/itab tables).
6. Distill `unstrip-ghidra-hints.json`: `prioritized_targets[]` (category+action), `itab_dispatch[]`, `struct_types[]` (fields+offsets), `xref_map{}`, `garble_assist{likely,decryptor_candidates[]}`, and **`annotations[]`** — for each target/struct/itab-site emit `{addr,kind,value,category,reason}`; kinds: `rename|signature_plate|plate_comment|inline_comment|decompiler_comment|struct_type|label|bookmark|function_tag`. Plate comments must be **analyst-actionable** (point at key/endpoint/related func addr).
7. `garble=likely` -> note in output that GoStringUngarbler should also run (the caller/main loop decides).

## Heuristics (NOT hardcoded)
- The suspicious-name list is a starting point, not a closed set - use judgment.
- `--data-at` targets: prefer addrs floss-filtered flagged as config/IOC, or non-trivial structs from unstrip-symbols.
- Annotate every `prioritized_target` + every `struct_type` + one `label`/`bookmark` per category cluster. Do NOT annotate thousands of runtime funcs.
- garble: if names look hashed, say so in `garble_assist`; **never fabricate** semantic names.

## Output
4 files in `evidence_dir`. Return a one-line summary: function count, garble verdict, #annotations.
