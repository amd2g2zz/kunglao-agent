---
name: kunglao-agent-memory-protocol
description: Memory architecture for kunglao-agent — two-tier staging → longterm distill with 10-item threshold and atomic clear
metadata:
  version: 1.0
  type: reference
---
**Heuristic**: are you writing raw evidence directly to facts/ or routing through the 2-tier pipeline (staging -> longterm)? If direct -> skip this file. If pipeline -> read on.


# kunglao-agent memory protocol

## Purpose

Per-session in-the-loop observations (successes / failures / discoveries) must
not disappear at session end, but they also must not pollute the global
`~/.claude/projects/.../memory/` ledger. This protocol defines a **two-tier
distill** flow:

```
worker observation (in-session)
    ↓ write to staging/<date>-<tag>.md
staging/   (project-specific, raw, claim-bound)
    ↓ 10 items accumulated → distill trigger
longterm/  (cross-project, distilled, rule-form)
    ↓ symlink to ~/.claude/projects/.../memory/ (or read by orchestrator)
global memory (consumed at session start by orchestrator)
```

## Two tiers, two distinct types

| Tier | Path | Content | Bound to |
|---|---|---|---|
| **staging/** | `memory/staging/` | Raw observation: symptom, repro, fix, why, claim/worker ID | One specific claim / worker / iteration |
| **longterm/** | `memory/longterm/` | Distilled rule: "in any kunglao-agent engagement, when X happens, do Y" | Cross-project, generic |

**Distillation rule**: a staging entry contains a claim ID (C-NN) or worker
ID (W-NN). A longterm entry strips these and replaces with a forward-looking
rule usable across all workspaces. Example:

| Tier | Entry |
|---|---|
| staging | `2026-07-31-F3-single-worker-focus.md` — claim C-047, orchestrator pings only last-dispatched W-47 while W-46 sits idle 34 min |
| longterm | `worker-fanout-monitoring.md` — when ≥2 workers are in flight, the heartbeat MUST enumerate ALL registered workers (no short-circuit on last-dispatched ID); see SKILL.md §6-pre F3 |

## Distill trigger — 10-item accumulation

**Rule**: the staging area accumulates freely. The distill pipeline does NOT
fire on every entry. It fires **only when staging contains ≥10 entries since
the last successful distill**. This avoids premature distillation and respects
the fact that individual observations are often redundant until they form a
pattern.

**Threshold enforcement**:
- `distill.py` reads `len(staging) >= 10` before doing anything
- `staging/INDEX.md` is the canonical counter (one line per entry, count = file count for sanity)
- Manual override: `--force` flag for user-triggered distill even below threshold (e.g. at session end before cleanup)

## Atomicity — staging clear is part of the distill transaction

**Rule**: distillation is an atomic transaction. Either everything happens
or nothing happens. Specifically:

```
1. LOCK         create staging/.distill.lock           (atomic, exclusive)
2. SNAPSHOT     cp staging/*.md staging/.snapshot/     (rollback point)
3. DISTILL      LLM/prompt reads 10 staging entries, writes 1 longterm entry
4. WRITE_LONGTERM append to longterm/<date>-distill-N.md + longterm/INDEX.md
5. VERIFY       confirm longterm file exists + INDEX.md updated + content hash matches
6. CLEAR_STAGING  rm staging/*.md (the 10 entries that were distilled)
                ↑ ONLY if step 5 passed
7. RELEASE      rm staging/.distill.lock
```

**Failure paths**:
- Step 3 fails (LLM error, parse error) → step 1-2 undone, no longterm write, no clear
- Step 4 fails (disk full, permission) → step 1-3 undone (longterm not updated)
- Step 5 fails (hash mismatch) → step 4 undone (longterm reverted), no clear
- Step 6 fails (rm fails) → step 4-5 STILL kept; staging is now in an inconsistent state with both old + new entries; manual recovery required (log B1d infra-blk + restore from staging/.snapshot/)

**Why step 6 is "ONLY if step 5 passed"**: if we clear staging before
verifying longterm, we lose the source data with no destination — the
exact failure that makes the rule load-bearing. The trade-off is "staging
might briefly have 10 duplicate entries after a partial failure" — but
that is **safer than losing them**.

## Staging entry schema

Each staging entry is a markdown file with YAML frontmatter:

```yaml
---
name: <kebab-case-slug>
description: <one-line summary used for INDEX.md>
metadata:
  node_type: memory
  type: feedback | success | failure | discovery  # required
  originSessionId: <uuid>
  modified: <ISO-8601 UTC>
  claim_id: <C-NN if applicable>     # optional
  worker_id: <W-NN if applicable>    # optional
  sample: <sha256 if applicable>     # optional
  confidence: 0.0-1.0                # optional, default 0.5
---
```

Body (markdown) MUST contain:

- **Symptom**: the specific observable behavior (not "things went wrong")
- **Repro**: how to reproduce (commands, claim ID, claim-register.yaml excerpt)
- **Fix applied**: file:line + (if applicable) commit hash
- **Why**: root-cause hypothesis
- **How to apply**: forward-looking rule

## Longterm entry schema

Same frontmatter + body, BUT:

- `type: feedback | success | rule | pattern` (rule / pattern only)
- `claim_id` and `worker_id` stripped (replaced with abstract category)
- Body's "Symptom" replaced with "Rule", "Repro" replaced with "Examples"
- `cross_project: true` (signals this entry is workspace-agnostic)
- **Link back** to staging/INDEX.md so the trail is auditable

## Index files

- `memory/staging/INDEX.md`: one line per staging entry (slug + date + type + claim_id)
- `memory/longterm/INDEX.md`: one line per longterm entry (slug + date + type + brief rule)

Append-only: never edit existing lines; rewrite the file to add a line at the end.

## Linkage to global `~/.claude/projects/.../memory/`

Longterm entries are **not auto-mirrored** to global memory. Instead, the
orchestrator at session start reads `memory/longterm/INDEX.md` and **on
demand** copies one entry to global memory when it has cross-workspace
utility. This avoids polluting global with project-specific distill outputs.

Two patterns:
1. **Long-term rule, generic** → copy to global as `kunglao-agent-<rule>.md`
2. **Long-term pattern, kunglao-agent specific** → keep in `memory/longterm/` only, orchestrator reads locally at session start

## Hook integration

`hooks/worker_budget.py` does NOT manage memory — that's a separate concern.
`scripts/distill.py` is the only writer to `longterm/`. Staging writes are
manual (orchestrator + worker via Write tool).

**Future hook**: a `PostToolUse` on `Write` that detects writes to
`memory/staging/*.md` and auto-appends to `memory/staging/INDEX.md`. Not
implemented yet — manual for now.

## What this is NOT

- Not a replacement for `progress.txt` or `notes/analysis_notes.jsonl` in
  the malware workspace. Those are RE-specific project artifacts.
- Not a replacement for per-session `~/.claude/projects/.../memory/MEMORY.md`.
  That ledger is human-curated, distinct from this auto-distill flow.
- Not a versioning system. `longterm/` entries can be edited in place; the
  rule is forward-looking, not historical.