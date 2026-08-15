# tools/pipelines — composition recipe templates + evidence index tool

This directory is the `pipelines` category's tool home, containing `recipes/*.yaml`: **plan-generation templates, not an executor**. A recipe is pure data (declaring "which registered tools chain in what order"); execution is carried by the individual registered tools (`tools/_INDEX.yaml`), and instantiation (generating `runs/plan-C<NN>.md`) is future wire-in work. Since #340, the pipelines category's registered tool `build_evidence_index.py` (`build-evidence-index`) is also homed here — the design constraint "recipes have no local executor" targets recipe instantiation only and does not bar registered tools from the category directory (#340 structure rule: tool scripts always live in their category directory).

## Relation to the index docs

A worker reads `tools/_index-pipelines.md` first (pipelines-domain tool contract entries, e.g. `build-evidence-index`); this README explains the recipe schema and directory. The machine contract is `tools/_INDEX.yaml` (recipes are pure-data templates, not registered).

## Recipe schema (schema: plan-recipe/1)

```yaml
schema: plan-recipe/1
id: stage-unpack                       # unique recipe id, kebab-case
title: Staged unpacking (stage-unpack)  # human-readable title
description: >-                        # when to use + what it does
steps:                                 # main chain: executed in order (>=1)
  - tool: ghidra-recon                 # tool name (tools/_INDEX.yaml) or capability query
    input: sample + packer/overlay markers   # this step's input (may carry arguments)
    output: packer verdict + section layout   # this step's output
fallback: [ghidra-decompile-functions, ghidra:recon]   # fallback chain if the main chain fails
verify: unpack-verify                  # verification hook name (must pass before the plan advances)
reuse_check: reuse existing unpack artifacts for a same-sha256 sample instead of unpacking again
```

- `steps[].tool` and `fallback[]` entries: **tool names** (must be registered in `tools/_INDEX.yaml`) or **capability queries** (`domain:op`, same semantics as `tools/tool-search.py --capability`: exact/prefix match). Capability queries are resolved to concrete tools via tool-search at instantiation; capabilities this repo does not yet have a tool for (e.g. `languages:go`) stay in the chain as queries.
- `verify`: verification hook name — instantiated as the verification step of runs/plan-C<NN>.md; if the hook does not pass, the plan must not advance (fail-closed). Currently only the name is declared; the hook is not implemented.
- `reuse_check`: reuse-criterion description — instantiated as a "check reuse first" step; if artifacts already exist, this recipe is skipped.
- Validation: `tests/test_recipes.py` enforces schema-key completeness + vocabulary consistency (every tool/fallback entry must hit the real index).

## Recipe catalog

| id | When to use (routing signal) | Instantiation artifact |
| --- | --- | --- |
| `stage-unpack` | overlay markers / packer markers (string_density + packer markers) | unpack-chain plan: ghidra-recon locates the packing layer → crypto-tool compression subcommands peel layers → disasm-constant-check validates |
| `crypto-decrypt` | crypto:decode signal (crypt32/bcrypt/advapi imports or a high-entropy section) | decrypt-chain plan: locate crypto APIs → crypto-tool algorithm decrypt → validate the plaintext layer |
| `syscall-chain` | dynamic intent (vm/run/execute/detonate or syscall keywords) | syscall-chain plan: locate call sites → decompile stubs → syscall-number assertion validation |
| `iat-chain` | iat intent (import/IAT keywords) | IAT-chain plan: parse the IAT → xref pointer scan → call assertion validation |
| `go-recovery` | languages:go markers (go.buildinfo / runtime.* hints) | Go-recovery plan: locate pclntab → go-byte-transform recovers symbols → validate the recovered layer |

## Instantiation (future wire-in)

Instantiation = generating `runs/plan-C<NN>.md` from a recipe (the claim plan file, following the existing runs/plan-C<NN>.md fill-in template role): each step expands to a plan entry (tool + input + output), `fallback` expands to fallback branches, `verify` expands to a verification gate, `reuse_check` expands to a reuse check. The wire-in lands in a later issue; there is no production consumer today (catalog reads are covered only by the `tests/test_recipes.py` contract test).

## Constraints

- Templates are pure data: no executor code, not registered in `tools/_INDEX.yaml`, no new state format created.
