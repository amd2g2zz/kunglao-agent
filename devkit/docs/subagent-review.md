# Subagent Review (Gate 5) - issue #462

> Single source of truth: Subagent Review schema and Gate 5 enforcement
> rule. The 3-element subagent contract (plan-to-execute / state-sync /
> tool-discovery + no-self-invention) is enforced for specialist agents
> (ghidra-light / floss-filter / pefile-signature / go-symbols /
> verdict-scorer) via a `.subagent-review/<id>.json` file. The local
> pre-commit hook enforces it.

## Why

issue #462 evidence 1 (ghidra-light worker field report, 2026-08-18):
- No plan-to-execute: worker jumped straight in
- No state-sync: bypassed worker-status / artifacts
- Self-invented tools: `scripts/ghidra/DecompileFuncs.java` (184 LOC) +
  `scripts/decompile_funcs_headless.py` (201 LOC) entered the working tree,
  while `ls scripts/re` already exposed 25+ existing RE tools

Evidence 2 (contract audit): of 5 specialist agents' `agents/*.md`,
plan / state / tool-discovery have **0 entries each** (kunglao-worker
alone has 12 / 6 / 2). Specialists are exactly the long-running,
high-blast-radius roles that need the contract.

## 3-element contract (all required)

| Field | Meaning | Anti-example (HARD_PAUSE) |
|---|---|---|
| `agent` | Which subagent (ghidra-light / floss-filter / ...) | Empty / "general-purpose with justification" (allowed but plan must be detailed) |
| `plan` | Pre-work plan (one line) | Empty |
| `status_sync` | Path to worker-status / artifacts file | Empty |
| `tools_used` | Array of RESOLVABLE tool citations: `scripts/re/**` (workspace namespace), a `tools/_INDEX.yaml` registered name, or a real file under `scripts/` `tools/` `references/` (`#anchor` allowed; a `tools/_INDEX.yaml#<name>` anchor must NAME a registered tool) | Empty, non-array, or a citation that resolves nowhere (self-invention signal, #493) |
| `verified_by` | Who did independent verification (anti self-stamp) | Contains "kunglao-agent" / "main" / "anthropic" / "claude" (orchestrator's own handle) |

## Gate 5 enforcement rule

- When staged changes touch `scripts/` / `hooks/` / `docs/` / `tests/`
  / `references/` / `skills/`, **at least one** `.subagent-review/*.json`
  must pass validation (5 fields + verified_by not self-stamp +
  tools_used non-empty + every citation resolvable)
- Missing / bad → HARD_PAUSE, local pre-commit hook refuses the commit
- No domain paths changed (openspec / pyproject / devkit scaffolding)
  → N/A, trivially passes

## Schema example

`.subagent-review/2026-08-19-ghidra-light-c409.json`:

```json
{
  "agent": "ghidra-light",
  "plan": "Decompile c-409 encrypted-string routine; produce pseudo-C and IAT cross-ref",
  "status_sync": "runs/worker-status-ghidra-light-c409.md",
  "tools_used": [
    "scripts/re/pseudo_c_extractor.py",
    "tools/_INDEX.yaml#ghidra-decompile-functions"
  ],
  "verified_by": "verifier-subagent-2026-08-19-c409"
}
```

## Trigger flow

1. Orchestrator dispatches specialist subagent
2. Subagent writes plan (in `runs/worker-status-*.md` plan section) before
   any work
3. Subagent completes -> writes `.subagent-review/<commit-sha-prefix>-<agent>.json`
4. Independent verifier subagent cross-checks -> writes `verified_by`
5. Orchestrator commits -> pre-commit hook runs Gate 5:
   - Validate 5 fields + verified_by not self-stamp + tools_used non-empty
     + every citation resolvable (#493: `scripts/re/**` prefix / registered
     `_INDEX.yaml` name / real file under scripts-tools-references, `#anchor`
     allowed; traversal and anchor-only citations never resolve; a
     `tools/_INDEX.yaml#<name>` anchor must name a registered tool —
     #493 LOW patch)
   - All pass -> commit succeeds
   - Any fail -> HARD_PAUSE, orchestrator fixes

## Invariants

- File is `.subagent-review/<id>.json` — single JSON, uncommitted is fine
  (it's pre-commit evidence)
- Field names are contract — schema upgrades go through openspec
- `verified_by` is substring-matched (not strict equality) to tolerate
  legitimate variants
- Resolvability is fail-closed toward the strict side: a missing/broken
  `tools/_INDEX.yaml` yields an empty name set (bare names unresolvable),
  and `tools_used` must be an array — a bare string fails (#493)
- An anchored index citation `tools/_INDEX.yaml#<name>` resolves only when
  `<name>` is a registered tool — a fabricated anchor riding the real index
  file is a self-invention signal (#493 LOW patch); anchors on other bases
  are stripped and ignored

## See

- issue #462 (contract origin)
- `devkit/subagent_review.py` (mechanical check implementation)
- `devkit/quality_gates.py` Gate 5
- `agents/kunglao-worker.md` 12 plan + 6 status + 2 tool-reuse
  contract entries (template for specialist agent upgrades)
