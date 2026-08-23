# tools/ toolshelf guide

> This directory is kunglao-agent's **toolshelf**: script tools + index contracts.
> Tools are classified into 6 capability domains, one progressive-disclosure index per domain; the machine contract is `_INDEX.yaml`, validated by `validate_index.py` (exit 0=pass / 1=fail, gate-callable).

## Reading order

After being dispatched a task, a worker reads in this order and **never needs to open any .py source**:

1. `tools/_INDEX.md` (category table) → pick a category;
2. `tools/_index-<category>.md` (per-tool contract entries: Purpose/Usage/Inputs/Outputs/exit code/when_not) → copy the usage command to construct the call;
3. `tools/_INDEX.yaml` (machine contract, consumed by gates/scripts).

This README is the **toolshelf guide** (for registrants/maintainers); it does not carry tool contracts.

## Structure rules (#340)

1. **Category id == directory name**: every `category` value in `_INDEX.yaml` must be named identically to the `tools/<category>/` directory (crypto/static/ghidra/auxiliary/pipelines);
   the sole exception is `dynamic` — the capability is provided over MCP + VM channels, with no local directory
   (#339 already deleted the vacuum shells `frida/` and `t2/`; do not recreate them).
   The alignment direction is the id follows the directory (not the other way): `aux` is a Windows reserved device name,
   so the directory can never be called `aux`; hence #340 renamed category ids `aux`→`auxiliary` and
   `pipeline`→`pipelines` (capability prefixes `aux:*`/`pipeline:*` are capability
   namespaces and do not follow category-id renames).
2. **Tool scripts always live in their category directory**: every registered tool's .py lives in `tools/<category>/`.
   The tools/ root layer allows only index/doc files (`_INDEX.md`/`_INDEX.yaml`/
   `_index-<category>.md`/`README.md`) plus the meta-tool exception below.
3. **Root-layer meta-tool exception (documented)**: `tool-search.py`,
   `validate_index.py`, and `ext-scan.py`
   stay at the tools/ root — they are the toolshelf's meta-tools, operating on
   the index files themselves (`tools/_INDEX.yaml` query/validation;
   `tools/_INDEX.ext.yaml` generation) rather than on samples, so they belong to no analysis category;
   `tool-search.py` and `validate_index.py` resolve their default index path as
   `Path(__file__).parent / "_INDEX.yaml"`,
   and being on the same level as `_INDEX.yaml` is part of that contract. `tool-search.py` and `ext-scan.py`
   are deliberately not registered in any
   index (the querier/generator does not enter the queried registry).
   The root layer also carries the ext-catalog data files
   (`_INDEX.ext.yaml` — generated, describe-only; `_INDEX.ext.map.yaml` —
   optional capability map; see "Ext catalog" below).
4. **Single shared-library point `tools/_lib/`**: pure library modules shared across categories (no CLI entry,
   not registered in the index) belong in `tools/_lib/` (currently: `lib_disasm.py`, the PE/capstone
   VA→offset core). Consumers add `tools/_lib` to `sys.path` themselves.
5. **One shared module per category**: each category directory holds at most one shared helper module
   (static: `common.py` — #340 already merged the original `common.py` (CLI plumbing) and
   `_common.py` (byte-scan helpers), keeping the whole public surface; crypto:
   `algorithms.py`; ghidra: `job_store.py`). Do not add a second shared module;
   extend the existing one.
6. **`__pycache__` stays out of the repo**: `.gitignore`'s `__pycache__/` + `*.pyc`
   apply at any depth under tools/ (mechanically verified via `git check-ignore`,
   asserted by `tests/test_tools_structure_340.py`).

Mechanical assertions for the structure contract are in `tests/test_tools_structure_340.py`.

## Directory layout

```text
tools/
├── _INDEX.yaml            # machine contract: tool registry (schema tools-index/1)
├── _INDEX.ext.yaml        # GENERATED describe-only catalog: repo capabilities outside the registry (#476)
├── _INDEX.ext.map.yaml    # optional name→capability map for the ext catalog (unmapped → unknown)
├── _INDEX.md              # top-level 6-category domain index (progressive-disclosure entry, styled after references/_INDEX.md)
├── _index-<category>.md   # per-category contract entries (per-tool H3 entry, 6 required segments); filename == category id
├── README.md              # this document: structure rules + directory layout + contract fields + MD format rules + registration flow
├── tool-search.py         # meta-tool (root-layer exception): deterministic query over _INDEX.yaml (+ --find over the ext catalog), not registered in the index
├── validate_index.py      # meta-tool (root-layer exception): machine-contract validator for _INDEX.yaml
├── ext-scan.py            # meta-tool (root-layer exception): ext-catalog generator (--check detects drift)
├── _lib/                  # cross-category shared-library single point: lib_disasm.py (PE/capstone VA→offset)
├── crypto/                # crypto category: crypto-tool.py + algorithms.py (shared module)
├── static/                # static category: static CLIs + shared common.py (#340 dual-module merge) + yara-rules/
├── ghidra/                # ghidra category: run_ghidra_postscript.py + postScript Java sources + job_store.py
├── auxiliary/             # auxiliary category: sanitize/audit/capture/measure tools
└── pipelines/             # pipelines category: build_evidence_index.py
```

6 capability domains:

| Category | Meaning | Example tools |
|---|---|---|
| `crypto` | encryption/decryption/encoding/hashing | `crypto-tool` |
| `static` | static identification/trait extraction | `die-probe`, `pe-analyze`, `yara-scan` |
| `ghidra` | Ghidra disassembly/function analysis | the 5 `ghidra-recon` family tools |
| `dynamic` | VM dynamic debugging/runtime analysis (**VM-only**, no local directory) | `x64dbg-remote`, `frida-remote` (MCP-provided) |
| `pipelines` | evidence index/report pipeline | `build-evidence-index` |
| `auxiliary` | auxiliary/miscellaneous | `sanitize-text`, `measure-cold-start` |

### External capabilities (not on this toolshelf, not registered in `_INDEX.yaml`)

- **Frida dynamic instrumentation**: MCP `mcp__frida__*` + VM channel `192.168.20.128:1337`; hook templates in `templates/frida/`.
- **x64dbg remote debugging**: MCP `mcp__x64dbg__*` (`connect_remote` only; all other calls forbidden on the host).
- **T2 emulation/simulated execution** (Qiling/unicorn): external skill `/malware-framework`.

### Ext catalog (`_INDEX.ext.yaml`, describe-only — issue #476)

Capabilities that live OUTSIDE this toolshelf registry but are callable repo
surface: entry-point `scripts/` CLIs, `hooks/` gates, and
`references/re-library/` capability-declaration docs. Enumerated
mechanically by `ext-scan.py` (AST `__main__` entry-point detection — no
filename lists) into `_INDEX.ext.yaml`; each entry carries
`name / capability / source / usage / description`.

- **Zero new trust mechanism**: entries are DESCRIBED, never executed from
  the index. Consumption is read/print (`tool-search.py --find <keyword>`,
  the mechanical query face of the #494 "search before you build" contract)
  and citation resolution (Gate 5 `tools_used` may cite an ext logical name).
- **Capability map is optional**: `_INDEX.ext.map.yaml` tags well-known
  names; unmapped entries surface as `capability: unknown` and stay
  discoverable by keyword (name/description/usage/source matching).
- **Consistency**: Gate 7 sub-check (d) fails on dangling source paths /
  malformed entries / collisions with internal registered names, and warns
  when an entry-point file is missing from the catalog. Fix for both:
  `uv run python tools/ext-scan.py` (never hand-edit the generated file).
- **Environment-side mcp entries (#515)**: `ext-scan.py --with-mcp
  <probe.json>` merges a `scripts/mcp_probe.py --mcp-inventory` document
  (registered MCP servers — the camoufox/gitnexus/playwright class) as
  entries named `mcp__<server>` carrying the `claude-json` **provenance
  label** (not a repo path; Gate 7 checks the label against
  `ENV_PROVENANCE_SOURCES` plus the `mcp__<server>` name shape instead of
  file existence). Still describe-only — mcp-ness is the structural
  `mcp__` name prefix, `--find` projects `kind: mcp`, `tools_used` may
  cite `mcp__<server>`. The **committed** index is regenerated WITHOUT
  the flag (environment face is per-machine; never commit it).

### Vacuum-shell disposition record (#339)

- `tools/frida/` (README only, no .py/.tmpl/.js/.yaml artifacts) → deleted; Frida capability is provided over MCP + VM channels, templates in `templates/frida/`.
- `tools/t2/` (README only) → deleted; T2 emulation capability is provided by the external skill `/malware-framework`.
- `tools/pipelines/` (README + build_evidence_index.py) → kept (#352 deleted the 5 plan-generation templates — zero runtime consumers; the registered tool remains).

## Contract field meanings (each `_INDEX.yaml` entry)

| Field | Required | Type / enum | Meaning |
|---|---|---|---|
| `name` | yes | string, unique | tool name, lowercase kebab-case |
| `category` | yes | `crypto\|static\|ghidra\|dynamic\|auxiliary\|pipelines` | capability domain (id == directory name, decides which `_index-<cat>.md` it belongs to) |
| `capability` | yes | `"<domain>:<operation>"` | capability tag, e.g. `crypto:decode` |
| `tier` | yes | `T1\|T2\|T3` | execution tier: T1=static tool / T2=emulated execution / T3=VM dynamic |
| `cost_tier` | yes | `probe\|cheap\|deep` | cost band: probe=seconds-fast check / cheap=minutes / deep=heavy tool or VM session |
| `input_output` | yes | non-empty str or `{input, output}` | input→output contract (machine-parseable) |
| `when_not` | no | non-empty string | when NOT to use this tool (negative-selection hint) |

Validation rules are in `validate_index.py` (name unique / category within the 6 / tier enum / cost_tier enum / input_output non-empty; optional fields, when present, must be non-empty).

## MD format rules (#339, apply to all markdown under tools/)

1. **Heading levels**: each file has exactly 1 `#` (H1, the file title); sections use `##` (H2); each per-tool contract entry uses `###` (H3, the heading is the tool name); H4 and deeper are forbidden.
2. **Contract-entry template** (each `_index-<category>.md` entry, fixed segment order):
   - **Purpose**: one sentence
   - **Usage**:
     (fenced code block: a directly copyable command with all required arguments; first line `python tools/...` or `mcp__...`)
   - **Inputs**: input shape and required arguments
   - **Outputs**: output shape (JSON/listing/file)
   - **exit code**: three-state semantics (0 success / 1 negative finding / 2 error; a few tools define their own, see the entry)
   - **when_not**: consistent with _INDEX.yaml's when_not
3. **Tables**: only for overview listings (category table/tool catalog); usage commands never go into tables (they go into fenced code blocks); no line breaks or unescaped `|` inside cells.
4. **Lists**: `-` for unordered, `1.` for ordered; nesting ≤2 levels.
5. **Language policy** (R3 #357): terminology (tool names/argument names/file paths/field names/exit codes) stays in its authoritative form; explanatory prose is English; do not append parenthetical translations after terms (the term is the authoritative name).
6. **Single authority**: a tool's contract appears exactly once, in `_index-<category>.md`; every other document references it without copying; `_INDEX.yaml` is the sole machine-contract authority, and md must not conflict with it.

Mechanical assertions for format and contracts are in `tests/test_index_docs_contract.py`.

## How to register a new tool

1. Append an entry to the `tools:` list in `tools/_INDEX.yaml` (see the commented example at the top of the file), filling in `name` / `category` / `capability` / `tier` / `cost_tier` / `input_output`, plus `when_not` as needed.
2. Append a contract entry to the domain's `tools/_index-<category>.md` (the 6-segment format of the "contract-entry template" above, `### <name>` heading) and add a row to its "tool catalog" table.
3. If it is a new capability domain, first update `tools/_INDEX.md`'s Category table + Per-category index files, then create the `tools/_index-<cat>.md` skeleton.
4. Validate:
   ```bash
   python tools/validate_index.py   # exit 0=pass / 1=fail (prints the error list)
   ```

## Discipline

- `_INDEX.yaml` is the **sole authoritative** machine registry; `_index-*.md` are human-facing disclosure indexes and must not conflict with the yaml.
- `dynamic`-domain tools are VM-only, always (see the CLAUDE.md hard constraint); registered `tier` must be `T3`.
- Contract-field add/remove/change must update `validate_index.py` + `tests/test_validate_index.py` in sync (TDD: RED first); entry-format add/remove/change must update `tests/test_index_docs_contract.py`.
