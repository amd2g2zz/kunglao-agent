---
name: go-symbols
description: "Stage 3.9 Go symbol recovery via unstrip (Go samples only, die.json language=Go). Runs unstrip --info / default / --format ghidra / --xref / --data-at, parses output, and WRITES evidence/unstrip-info.json + unstrip-symbols.json + unstrip-ghidra-apply.py + unstrip-ghidra-hints.json. The hints file carries prioritized_targets + itab_dispatch + struct_types + xref_map + garble_assist + annotations[] (the persistent mark-up plan ghidra-light applies to the Ghidra project). Heuristic not hardcoded - you classify functions, pick --data-at targets, and craft actionable annotations. Pure local. You DO have the Write tool - write the files yourself, do not return YAML to the caller."
# mechanical trigger table — parsed by scripts/route_capability.py.
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

## Subagent contract (structural declaration)

<!-- contract: plan-to-execute -->
Pipeline step 1: sequentialthinking preamble BEFORE running unstrip — confirm
Go, pick suspicious-name patterns, choose `--data-at` targets from prior evidence.
Update the plan when the data argues otherwise, then continue.

**Plan FIRST, in writing**: your first action is to create
`runs/worker-status-go-symbols-<id>.md` and write its plan section BEFORE
running `unstrip` (the sequentialthinking preamble lands THERE, in
writing). The plan section states, in this domain's language: (a) what you
will do — the unstrip subcommand sequence (`--info` → default → `--format
ghidra` → `--xref` / `--data-at`) and the name patterns you will classify
into decrypt / c2 / loader / persistence / exfil / recon; (b) expected
artifacts — per file: `unstrip-info.json` (go_version / pclntab addr+size /
function_count / garble verdict), `unstrip-symbols.json` (Layer A counts +
Layer B `suspicious_functions[]`), `unstrip-ghidra-apply.py` (VERBATIM
export), `unstrip-ghidra-hints.json` (`prioritized_targets[]` +
`annotations[]` plan); (c) the done criterion — all four files exist and
the one-line summary matches them. Non-Go `die.json` → update the plan,
then stop degraded (`status: blocked`, not a silent skip).

<!-- contract: status-sync -->
WRITE the four evidence files yourself (`unstrip-info.json` /
`unstrip-symbols.json` / `unstrip-ghidra-apply.py` / `unstrip-ghidra-hints.json`);
return the one-line summary (function count, garble verdict, #annotations)
only after the files exist — a run without files has FAILED.

**Liveness + artifacts (canonical log / W-15 lesson)**: append to
`runs/worker-status-go-symbols-<id>.md` as an append-only log parsed by the
single canonical parse point (`hooks/lib_kunglao.py` — LAST `status:`
token wins). Canonical vocabulary ONLY — `status: in-progress` /
`status: done` / `status: blocked`. W-15: the `status: done` line MUST
declare the four deliverables — `| status: done | artifacts: <the four
evidence/unstrip-*.json / .py paths, comma-separated>` —
`lib_kunglao.scan_done_artifact_violations` re-verifies each declared path
exists; `artifacts: none` is a W-15 failure. Heartbeat: reply to the
orchestrator's ping in the same file with your current state — never let
a long unstrip parse be mistaken for "stuck" (time-based stall watchdog: `STUCK_MINUTES=20` — 20 min without a status-file update).

<!-- contract: tool-discovery -->
Reuse `unstrip` (PATH or the `analysis_state.txt` toolchain path) — do not
hand-roll pclntab parsing; garble assist names candidates, never fabricates
semantic names.

**Discovery before ANY new code**. Before writing any
parser or wrapper, run the three-point check: (1) `ls scripts/re` — the
workspace RE tools deployed for this engagement; (2) grep
`tools/_INDEX.yaml` by category/capability (`static:*`, `ghidra:*`); (3)
the matching `references/re-library/` file (`languages-go.md` for pclntab
/ garble / itab specifics).
Registered domain tools (verify in the index first): `go-buildinfo-carve`, `binary-sweep`, `stack-strings`, `disasm-dump`, `ghidra-evidence-annotations`.
Self-invention is forbidden: `unstrip` itself IS the pclntab tool — never
hand-roll symbol recovery; a missing capability = file an issue to
upstream it into `tools/`; a one-off shim must be labeled disposable and
dropped after the run.

