# Plan: Batch 4 — Reposition kunglao-agent to RE-only scope (remove CTI/intelligence phase)

## Summary

kunglao-agent currently frames itself partly as a malware-intelligence pipeline: it
dispatches `cti-correlator` (VirusTotal/CTI aggregation) and `shodan-host` (Shodan
pivots), and its `verdict-scorer` does **maliciousness classification + Admiralty/ACH/
Diamond attribution** (naming threat actors). None of that is reverse engineering — it
is CTI/OSINT. Per user correction: **kunglao-agent's job ends at "complete the reverse
engineering." CTI/attribution is a downstream, out-of-scope activity for a different
system.** This plan removes the CTI/intelligence phase from kunglao-agent's contract and
narrows `verdict` to what it should always have been: verifying that the fact base
correctly and completely answers the user's `task_spec.primary_questions`.

## User Story

As the kunglao-agent orchestrator,
I want my dispatch surface, verdict step, and contract docs to contain zero CTI/
attribution machinery,
So that every dispatch and every verdict is unambiguously about reverse-engineering
correctness/completeness, not threat intelligence.

## Problem → Solution

**Current**: `agents/cti-correlator.md` + `agents/shodan-host.md` are listed as
specialist-first agents (SKILL.md L115, L284); `agents/verdict-scorer.md` scores 6-dim
maliciousness → `classification` and runs Admiralty+ACH+Diamond → `attribution` (named
actor); DESIGN.md §6 lists "CTI 冷启动" / "CTI 交叉" as module pillars; `task_spec.yaml`
has `external_cti_query: forbidden|allowed` as a worker constraint.

**Desired**: cti-correlator/shodan-host are deleted from kunglao-agent's agent roster and
every reference to them. `verdict-scorer` reads the fact base + `task_spec.
primary_questions` and outputs whether each question is answered (with a PROVEN-FULL
cited fact) and whether the fact base is internally consistent — no `classification`, no
`attribution`, no actor naming. `verdict-redteam` mirrors: blind re-check of correctness/
completeness, not blind re-derivation of maliciousness/attribution. DESIGN.md module
table drops the CTI rows. `task_spec.yaml` drops `external_cti_query` (CTI queries are
never in scope, so there is nothing to toggle).

## Metadata

- **Complexity**: Large (touches contract docs + 2 agent deletions + 1 agent rewrite + schema + tests, but each task is mechanical, not novel design)
- **Source PRD**: N/A (user boundary correction, this session)
- **PRD Phase**: N/A
- **Estimated Files**: ~14 (2 deleted, 1 rewritten pair, 6 doc edits, 1 schema edit, ~4 test files)

---

## UX Design

N/A — internal orchestrator contract change, no user-facing UI. The user-visible effect
is behavioral: kunglao-agent will never dispatch a CTI/Shodan agent and `verdict.json`
will never contain a threat-actor name or malware classification.

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `SKILL.md` | 1-40 (frontmatter), 54-76 (Goal), 110-119 (5 behaviors incl. specialist-first list), 280-300 (local defaults agent table), 505-512 (module inventory + verdict line) | Contract surface that names cti-correlator/shodan-host/verdict-scorer's old role |
| P0 | `agents/verdict-scorer.md` | 1-274 (whole file) | Full rewrite target — every section (maliciousness dims, Admiralty ledger, Diamond, ACH, S5 gate) is attribution/malice machinery being replaced |
| P0 | `agents/verdict-redteam.md` | 1-84 (whole file) | Blind checker for verdict-scorer — must mirror the new correctness/completeness contract |
| P0 | `templates/task_spec.yaml` | 1-31 (whole file) | `external_cti_query` constraint (L22) and `need:` enum (L7) are the schema surface to edit |
| P1 | `DESIGN.md` | 88-98 (§6 module table), 297-302 (boundary_type/claim.source table) | CTI 冷启动/CTI 交叉 rows to remove; `claim.source` enum has `cti` — decide keep-as-historical-tag vs remove |
| P1 | `agents/cti-correlator.md` | 1-30 (frontmatter + opening) | Confirm scope before deletion (mal-recon Stage 3/3.5 aggregator — not RE) |
| P1 | `agents/shodan-host.md` | 1-30 (frontmatter + opening) | Confirm scope before deletion (Shodan host-page scraper — not RE) |
| P1 | `release-manifest.yaml` | 20-35 | Agent file manifest lists cti-correlator.md/shodan-host.md — must drop entries after deletion |
| P2 | `references/guardrails.md` | 325-335 | One specialist-list mention (§ line 331) |
| P2 | `references/convergence-loop.md` | 40-55 | "CTI correlation → cti-correlator" / "Verdict scoring → verdict-scorer" routing lines |
| P2 | `references/operational-mechanics.md` | 110-135 | Specialist bootstrap-tolerance list includes cti-correlator/verdict-scorer (verdict-scorer stays in the list, just its role text changes: no longer "scores maliciousness") |
| P2 | `tests/test_release_receipt.py`, `tests/test_global_rule_subset.py` | all | Check whether these assert on the agent roster / manifest contents — will need updates if they enumerate cti-correlator/shodan-host |

## External Documentation

No external research needed — this is a scope/contract edit using only the project's
existing conventions (openspec SDD + TDD, agent frontmatter format already used by every
other agent file in `agents/`).

---

## Patterns to Mirror

### AGENT_FRONTMATTER (existing agent file shape to follow when rewriting verdict-scorer)
```yaml
---
name: verdict-scorer
description: "<one paragraph — what it reads, what it writes, in imperative third-person>"
allowedTools:
  - Read
  - Grep
  - Write
  - mcp__sequential-thinking__sequentialthinking
disallowedTools:
  - Edit
  - NotebookEdit
  - Bash
  - WebFetch
  - WebSearch
isolation: none
---
```
SOURCE: `agents/verdict-scorer.md:1-15` (keep this frontmatter shape verbatim — only the
`description` and `name`'s conceptual role change, tools stay identical since the new
verdict still only reads `facts/*` + `task_spec.yaml` and writes one JSON file).

### DISPATCH_TABLE_ROW (how SKILL.md lists specialist agents)
```markdown
2. **Specialist agents first** — ghidra-light, cti-correlator, floss-filter, pefile-signature, verdict-scorer; general-purpose only when no specialist fits.
```
SOURCE: `SKILL.md:115`. Mirror this exact line shape when removing cti-correlator:
`ghidra-light, floss-filter, pefile-signature, go-symbols, verdict-scorer`.

### OUTPUT_JSON_SCHEMA (verdict.json shape convention — `_meta` + top-level keys)
```json
{
  "_meta": {"source": "verdict-scorer", "schema_version": "<date>-v<N>", "queried_at": "<ISO8601>", "methodology": "<doc ref>"},
  "sample_sha256": "<hash>"
}
```
SOURCE: `agents/verdict-scorer.md:57-64`. Mirror `_meta` block verbatim; replace
everything under it (`classification`/`attribution_evidence`/`diamond`/`ach`/
`attribution`) with the new `analysis_verdict` shape (see Task 4 below).

### CONSTRAINT_ENUM (task_spec.yaml constraint style)
```yaml
constraints:
  vm_detonation: forbidden      # forbidden | allowed
  time_budget_minutes: 120
  dynamic_re: allowed           # allowed | forbidden
```
SOURCE: `templates/task_spec.yaml:20-24`. Mirror this key: value # comment style; simply
delete the `external_cti_query` line (no replacement needed — CTI is never in scope, so
there is nothing to gate).

### TEST_STRUCTURE (openspec-change-in-PR pattern used by every prior batch issue)
SOURCE: `master-plan.md:203-213` — "Shipped via openspec-change-in-PR only" convention:
each issue creates `openspec/changes/<name>/` (proposal/design/specs/tasks) inside its own
worktree, then a focused `tests/test_<name>.py`, no separate plan file required beyond
this batch plan. Mirror that — do not create 8 more per-issue `.plan.md` files.

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `agents/cti-correlator.md` | DELETE | CTI aggregation, not RE — out of scope per boundary correction |
| `agents/shodan-host.md` | DELETE | Shodan OSINT pivot, not RE — out of scope |
| `agents/verdict-scorer.md` | REWRITE | Strip maliciousness (6-dim/classification) + attribution (Admiralty/ACH/Diamond/S5 gate); replace with correctness/completeness verifier against `task_spec.primary_questions` |
| `agents/verdict-redteam.md` | REWRITE | Mirror verdict-scorer's new contract — blind re-check of PQ-coverage + fact-citation validity, not blind re-derivation of malice/attribution |
| `SKILL.md` | UPDATE | L115 specialist list, L284 local-defaults agent table, L505-512 module inventory + verdict line, Goal section (L54-76) reframed as PQ-completeness-agnostic-of-domain, add explicit non-goal line |
| `DESIGN.md` | UPDATE | §6 module table (L88-98) drop CTI 冷启动/CTI 交叉 rows; verdict row description change; `claim.source` table (L302) — keep `cti` enum value as historical/inert (no functional path reads it after cti-correlator deletion) but do not expand it |
| `templates/task_spec.yaml` | UPDATE | Delete `external_cti_query` constraint line (L22); no `need:` enum change required — `model_selection`/`yes_no_with_evidence`/`protocol_description` already domain-agnostic (they were never malware-specific, so no expansion needed here — see Task 2 rationale) |
| `references/guardrails.md` | UPDATE | L331 specialist-list mention — drop cti-correlator/shodan-host |
| `references/convergence-loop.md` | UPDATE | L48, L51 — drop "CTI correlation → cti-correlator" routing line; keep "Verdict scoring → verdict-scorer" (role text implicitly changes via the agent rewrite, no wording needed here beyond removing the CTI line) |
| `references/operational-mechanics.md` | UPDATE | L130-131 specialist bootstrap-tolerance list — drop cti-correlator (verdict-scorer/ghidra-light/floss-filter/pefile-signature/go-symbols remain) |
| `release-manifest.yaml` | UPDATE | Drop `agents/cti-correlator.md` (L26) and `agents/shodan-host.md` (L28) entries |
| `tests/test_release_receipt.py` | UPDATE (if applicable) | Check for agent-roster assertions referencing deleted files |
| `tests/test_global_rule_subset.py` | UPDATE (if applicable) | Check for CTI-agent references in the global-rule subset check |
| `tests/test_verdict_scorer_contract.py` (NEW, or existing renamed) | CREATE/UPDATE | RED→GREEN tests for the new verdict schema (no `classification`/`attribution` keys; new `analysis_verdict` key present; PQ-coverage logic tested) |

## NOT Building

- NOT touching `references/re-library/malware-analysis*.md`, `malware-dynamic-analysis.md`,
  `malware-triage.md`, `malware-report-writer.md` — these are RE **techniques** for
  analyzing malware samples (static/dynamic analysis method), which stays in scope
  because malware analysis is a RE subset. Only the CTI/attribution/OSINT layer is removed.
- NOT adding firmware/game/UEFI/WASM/RISC-V to re-library scope (explicit user "不需要" —
  out of scope for this plan and for any future absorption batch).
- NOT building a new external-CTI-system integration or handoff contract — if a user wants
  CTI/attribution after kunglao-agent converges, that is a separate tool/skill invocation
  outside this project, not something kunglao-agent calls or waits on.
- NOT changing the convergence loop, priority.py, claim-register schema, or any of the
  batch-1/2/3 shipped mechanics — this plan is purely the CTI/verdict scope cut.
- NOT re-litigating `claim.source: cti` enum value's full removal — leaving it as an inert
  historical tag avoids a wider schema-migration ripple (facts/claim-register written by
  earlier sessions may already use it); no code path will produce it going forward once
  cti-correlator is deleted.

---

## Step-by-Step Tasks

### Task 1: Delete cti-correlator and shodan-host agents
- **ACTION**: `git rm agents/cti-correlator.md agents/shodan-host.md`
- **IMPLEMENT**: Straight deletion — no replacement content, no stub.
- **MIRROR**: N/A (deletion, not code)
- **IMPORTS**: N/A
- **GOTCHA**: `agents/kunglao-worker.md` and `agents/go-symbols.md` also mention
  `cti-correlator`/`mal-recon` in passing (grep confirmed) — check if those mentions are
  load-bearing routing instructions (worker told to hand off to cti-correlator) vs. just
  a stray reference; strip the routing instruction if present, leave narrative-only
  mentions of `mal-recon` (an external CTI harness kunglao-agent is not part of) as-is
  since `mal-recon` itself is not being deleted, only kunglao's dispatch of its CTI stage.
- **VALIDATE**: `grep -rn "cti-correlator\|shodan-host" agents/ SKILL.md DESIGN.md references/ release-manifest.yaml` returns zero hits after Task 1+5+6+9+10 land (this task alone will still show hits in the doc files — that's expected, cleaned in later tasks).

### Task 2: Rewrite verdict-scorer.md contract
- **ACTION**: Replace the entire file body (keep frontmatter tool list unchanged per
  AGENT_FRONTMATTER pattern) with a correctness/completeness verifier.
- **IMPLEMENT**: New responsibilities:
  1. Read `task_spec.yaml` (`primary_questions[]`) + `claim-register.yaml` + `facts/*.md`
     (+ `facts/_INDEX.md`).
  2. For each `primary_questions[].id`: find the fact(s) with `answers_question: <id>`;
     require `status: PROVEN` **and** `confidence_band: PROVEN-FULL` (mirror C0a's own
     rule from DESIGN.md §8 — verdict does not invent a laxer bar than convergence
     already enforces); if `need: model_selection`, require the competitor_group
     resolution described in C0b (≥1 terminal + rest REFUTED/DEFERRED).
  3. Cross-check internal consistency: no two PROVEN facts on the same topic without a
     `supersedes`/`CONFLICT` resolution (reuse the existing `fact_contradiction_gate.py`
     output if present — verdict-scorer is a Read-only consumer, it does not re-implement
     #47's gate).
  4. Emit `evidence/verdict.json` with:
     ```json
     {
       "_meta": {"source": "verdict-scorer", "schema_version": "<today>-v11", "queried_at": "<ISO8601>", "methodology": "task_spec.primary_questions coverage + fact-citation validity"},
       "sample_sha256": "<hash>",
       "analysis_verdict": {
         "complete": true,
         "correct": true,
         "primary_questions": [
           {"id": "q1", "answered": true, "cited_fact": "F012", "confidence_band": "PROVEN-FULL", "gap": null}
         ],
         "unresolved": [],
         "contradictions": [],
         "degraded": [{"reason": "<>", "affected_question": "<id>"}]
       },
       "self_audit": {"evidence_strength": "strong|mixed|weak", "ignored_evidence": [], "open_questions": []}
     }
     ```
  5. Delete every maliciousness/attribution section: `classification`, `diamond`, `ach`,
     `attribution`, `attribution_evidence`, the 6 scoring-dimension subsections, the
     Admiralty ledger reasoning, the S5 gate, the harness-confound table, all
     "Anti-Patterns" entries about scoring/naming an actor.
  6. Update Provenance footer: `v11 (<today>): maliciousness/attribution removed per
     scope boundary correction — kunglao-agent verifies RE analysis correctness/
     completeness against task_spec.primary_questions, not threat classification.`
- **MIRROR**: AGENT_FRONTMATTER + OUTPUT_JSON_SCHEMA patterns above.
- **IMPORTS**: N/A (markdown agent contract file, no code imports)
- **GOTCHA**: Do not silently drop the `degraded[]` self-honesty convention — it is a good
  pattern (mirrors #78's fail-closed philosophy: don't claim complete when data is
  missing) and should carry over into the new schema as shown.
- **VALIDATE**: `agents/verdict-scorer.md` contains zero occurrences of
  `maliciousness|attribution|Admiralty|Diamond|ACH|classification|named_actor` after
  rewrite: `grep -ic "maliciousness\|attribution\|admiralty\|diamond\|\bach\b\|classification\|named_actor" agents/verdict-scorer.md` → `0`.

### Task 3: Rewrite verdict-redteam.md to match
- **ACTION**: Update the blind-checker contract to re-derive PQ-coverage/correctness
  independently, not maliciousness/attribution.
- **IMPLEMENT**: verdict-redteam reads `task_spec.yaml` + `facts/*.md` (raw evidence) —
  never `evidence/verdict.json` (maker-checker: it must not read the maker's conclusion).
  It independently determines: for each primary_question, is there a PROVEN-FULL fact
  answering it? Is there an unresolved contradiction? It reports its own verdict, and the
  orchestrator diffs the two (existing `verdict-compare.py` pattern, if present, else a
  simple field-by-field diff) — CONFIRMED / REFUTED / DIFF, same maker-checker discipline
  already used elsewhere in this project.
- **MIRROR**: `agents/verdict-redteam.md:1-20` (existing "BLIND adversarial checker...
  WITHOUT reading verdict-scorer's conclusion" framing — keep that sentence structure,
  swap "maliciousness + attribution" for "primary-question coverage + correctness").
- **IMPORTS**: N/A
- **GOTCHA**: If a `scripts/verdict-compare.py` or similar diff tool exists and hardcodes
  `classification`/`attribution` field names, it needs the matching field-name update —
  search for it before assuming the diff step is doc-only.
- **VALIDATE**: `grep -ic "maliciousness\|attribution" agents/verdict-redteam.md` → `0`.

### Task 4: Update SKILL.md contract surface
- **ACTION**: Edit 4 locations.
- **IMPLEMENT**:
  - L54-76 (Goal): after "The output that matters is a fact base..." add one sentence:
    "Verdict — once the fact base converges — means verifying every `task_spec.
    primary_questions` entry is answered by a PROVEN-FULL fact and the fact base has no
    open contradiction; it is never a maliciousness or threat-actor judgment."
  - L115 (behavior #2 specialist list): `ghidra-light, cti-correlator, floss-filter,
    pefile-signature, verdict-scorer` → `ghidra-light, floss-filter, pefile-signature,
    go-symbols, verdict-scorer`.
  - L284 (local defaults agent table row): `kunglao-worker`, `ghidra-light`, `go-symbols`,
    `pefile-signature`, `floss-filter`, `cti-correlator`, `shodan-host`, `verdict-scorer`
    → `kunglao-worker`, `ghidra-light`, `go-symbols`, `pefile-signature`, `floss-filter`,
    `verdict-scorer`.
  - L505-512 (module inventory table): remove the "CTI 冷启动" and "CTI 交叉" rows if
    present in this exact file (confirmed present in DESIGN.md §6 — check whether
    SKILL.md's own inventory line at L510 duplicates it: currently reads "CTI cold-start
    (read-only) · sample-class detection ... · verdict (verdict-scorer agent, optional
    post-convergence)" — delete the "CTI cold-start (read-only) ·" segment entirely, it
    is the only CTI mention in SKILL.md's own table).
  - Add to "What the orchestrator is NOT" section (search for that heading): a new
    bullet — "It does not query CTI/OSINT sources, extract IOCs, or attribute to a threat
    actor. That is out of scope; kunglao-agent's job ends at a byte-anchored, verified RE
    fact base."
- **MIRROR**: DISPATCH_TABLE_ROW pattern above for L115/L284.
- **IMPORTS**: N/A
- **GOTCHA**: SKILL.md is already at 560 lines vs the 500-line contract test
  (`test_contract_docs::test_skill_lte_500_lines`, a pre-existing known failure per
  master-plan.md rev 15/23 — do NOT let this edit grow the file further; net effect here
  should be roughly neutral or a slight reduction (removing more text than the one new
  non-goal bullet adds). If it grows, trim adjacent redundant prose in the same pass —
  but do not attempt to fix the pre-existing >500 line failure as part of this batch
  (out of scope, tracked separately).
- **VALIDATE**: `grep -n "cti-correlator\|shodan-host\|CTI cold-start" SKILL.md` → no
  output. `wc -l SKILL.md` ≤ prior line count (560) + 3.

### Task 5: Update DESIGN.md module table
- **ACTION**: Edit §6 module table (L88-98).
- **IMPLEMENT**: Delete the "CTI 冷启动(只读)" row and the "CTI 交叉" row entirely
  (2 table rows). Update the "裁决(收敛后可选)" row's description from `verdict-scorer
  agent` (unchanged agent name, but the footnote "注:`cti-correlator` / `verdict-scorer`
  是 agent type,非 skill" — update to drop the now-deleted `cti-correlator` from that
  footnote, keep it for `verdict-scorer`).
- **MIRROR**: Existing markdown table row shape, no new pattern needed.
- **IMPORTS**: N/A
- **GOTCHA**: DESIGN.md is explicitly documented as historical/lagging ("this SKILL.md
  is the operative contract when they disagree" — SKILL.md L46) — but per the existing
  convention (batch-3 rev 25 etc.) DESIGN.md still gets updated for major contract shifts
  like this one (it was updated for #88's isolation-first contract). Do the same here;
  do not skip it as "just historical."
- **VALIDATE**: `grep -n "CTI 冷启动\|CTI 交叉\|cti-correlator" DESIGN.md` → no output
  (verdict-scorer mentions remain, that's expected).

### Task 6: Update task_spec.yaml template
- **ACTION**: Delete `external_cti_query` constraint line.
- **IMPLEMENT**: Remove `templates/task_spec.yaml:22` (`external_cti_query: forbidden #
  forbidden | allowed — 只读现有 CTI 时 forbidden`) entirely. No replacement key needed
  — since kunglao-agent never queries CTI, there is nothing to toggle; leaving a
  vestigial always-`forbidden` key would be dead config.
- **MIRROR**: CONSTRAINT_ENUM pattern (surrounding lines untouched, same YAML comment
  style).
- **IMPORTS**: N/A
- **GOTCHA**: Search `scripts/` for any code reading `constraints.external_cti_query`
  (the PreToolUse hook at DESIGN.md L232 mentions comparing `intended_tools` against
  `task_spec.constraints` generically — check `hooks/worker_budget.py` for a literal
  `external_cti_query` key lookup before deleting, to avoid an orphaned schema reference
  a script still expects).
- **VALIDATE**: `grep -rn "external_cti_query" . --include="*.py" --include="*.yaml"`
  (excluding `.venv/`) → no output anywhere in the repo after this task + any script fix
  it surfaces.

### Task 7: Update references/*.md specialist mentions
- **ACTION**: 3 files, 1 line each.
- **IMPLEMENT**:
  - `references/guardrails.md:331` — drop `cti-correlator`/`shodan-host` from the
    specialist enumeration (keep `floss-filter`/`verdict-scorer`).
  - `references/convergence-loop.md:48` — delete the "CTI correlation → `cti-correlator`"
    routing line; keep L51 "Verdict scoring → `verdict-scorer`" unchanged (role text
    change lives in the agent file itself, not this routing pointer).
  - `references/operational-mechanics.md:130-131` — drop `cti-correlator` from the
    specialist bootstrap-tolerance list (`verdict-scorer, ghidra-light, floss-filter,
    pefile-signature, go-symbols` remains, minus cti-correlator).
- **MIRROR**: Existing list/table formatting in each file, unchanged otherwise.
- **IMPORTS**: N/A
- **GOTCHA**: `operational-mechanics.md:117-122` also narrates a specific incident
  ("C-332... a freshly-dispatched verdict-scorer was...") — this is historical case
  evidence, do not rewrite the narrative, only the specialist list at L130-131.
- **VALIDATE**: `grep -rln "cti-correlator\|shodan-host" references/` → no output.

### Task 8: Update release-manifest.yaml
- **ACTION**: Remove 2 manifest entries.
- **IMPLEMENT**: Delete `agents/cti-correlator.md` (L26) and `agents/shodan-host.md`
  (L28) lines from the tracked-file manifest list.
- **MIRROR**: Existing YAML list-item formatting, unchanged.
- **IMPORTS**: N/A
- **GOTCHA**: If any release/CI check (`scripts/` or `.github/workflows/release-check.yml`)
  cross-validates that every file in `agents/` appears in this manifest (or vice versa),
  re-run that check after Task 1 + this task to confirm no orphaned entry / no
  untracked-but-present file.
- **VALIDATE**: `grep -n "cti-correlator\|shodan-host" release-manifest.yaml` → no output.

### Task 9: Update/add tests
- **ACTION**: Audit and fix `tests/test_release_receipt.py`,
  `tests/test_global_rule_subset.py`, plus any test asserting on the old verdict schema;
  add new RED→GREEN tests for the rewritten verdict-scorer contract.
- **IMPLEMENT**:
  1. `grep -rln "cti-correlator\|shodan-host\|classification\|attribution" tests/` —
     for every hit, determine if it's asserting on the removed surface (fix/delete the
     assertion) or an unrelated identifier collision (leave alone).
  2. New test file `tests/test_verdict_contract.py` (or extend an existing verdict test
     if one exists — check first): RED tests that (a) `evidence/verdict.json` schema
     validation rejects a payload containing `classification`/`attribution` keys (schema
     drift guard, mirrors the project's existing schema-drift discipline from #97's
     `schemas/convergence-check-output.json`), (b) a fixture with all `primary_questions`
     PROVEN-FULL-cited produces `analysis_verdict.complete: true`, (c) a fixture with one
     unanswered PQ produces `complete: false` + that PQ listed in `unresolved`, (d) a
     fixture with a same-topic contradiction produces a non-empty `contradictions[]`.
  3. GREEN: implement whatever thin scoring/schema-check script the tests need (if
     verdict logic is currently pure-agent-prompt with no backing script, add a JSON
     Schema file `schemas/verdict-output.json` mirroring the #97 precedent, and a
     `scripts/test_verdict_contract.py`-checkable validator — this keeps verdict
     mechanically checkable rather than purely LLM-self-reported, consistent with this
     project's "机械门禁优先" convention from `maker-checker.md`).
- **MIRROR**: `schemas/convergence-check-output.json` + `tests/test_decide_schema_
  routing.py` (the #97 precedent for "schema exists + behavioral tests enforce it").
- **IMPORTS**: `json`, `jsonschema` (or whatever validation lib the #97 precedent used —
  check its imports before adding a new dependency).
- **GOTCHA**: Do not invent a new schema-validation library if one is already a project
  dependency for #97's schema — reuse it.
- **VALIDATE**: `pytest tests/test_verdict_contract.py tests/test_release_receipt.py
  tests/test_global_rule_subset.py -v` → all pass; full suite unaffected count-wise
  (baseline + N new tests, same 2 pre-existing failures as documented in master-plan.md).

### Task 10: Final repo-wide sweep + openspec change
- **ACTION**: Create `openspec/changes/reposition-re-only-scope/` (proposal/design/specs/
  tasks) documenting this batch as one SDD change (or one change per issue if filed as
  separate GitHub issues — follow the existing "one issue → one PR → one branch → one
  worktree" convention; this task assumes the batch is filed as issues #R1-#R9 mapping
  1:1 to Tasks 1-9 above, each in its own worktree named `kunglao-agent`).
- **IMPLEMENT**: Run the repo-wide grep sweep from Task 1's VALIDATE step across the
  *entire* repo (not `.venv/`) one final time after all tasks land, to catch anything
  missed (e.g. `docs/refactor/design-spec.md` and `openspec/changes/release-contract/*`
  — confirmed hits during research — these are historical openspec-change artifacts from
  *already-shipped* issues; leave them untouched, they are immutable history, not live
  contract).
- **MIRROR**: master-plan.md's own "Delta log" revision-entry convention — after this
  batch ships, append a new revision entry to `master-plan.md` documenting it (per this
  project's living-document discipline).
- **IMPORTS**: N/A
- **GOTCHA**: `openspec/changes/release-contract/*` and `openspec/changes/icd203-source-
  reliability/*` contain `cti-correlator`/`attribution` text — these are **frozen
  artifacts of already-merged, already-closed issues** (per master-plan.md's own rule:
  historical openspec changes are not rewritten). Do not touch them; only live contract
  surfaces (SKILL.md, DESIGN.md, agents/, references/, templates/, release-manifest.yaml)
  are in scope.
- **VALIDATE**: `grep -rln "cti-correlator\|shodan-host" --include="*.md" --include="*.py" --include="*.yaml" . | grep -v ".venv\|openspec/changes/release-contract\|openspec/changes/icd203-source-reliability"` → no output.

---

## Testing Strategy

### Unit Tests

| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| `test_verdict_schema_rejects_classification_key` | verdict.json payload with `classification` key | schema validation FAIL | yes — regression guard against old shape resurfacing |
| `test_verdict_schema_rejects_attribution_key` | verdict.json payload with `attribution` key | schema validation FAIL | yes |
| `test_verdict_all_pq_proven_full` | fixture: 2 PQs, both cited by PROVEN-FULL facts | `analysis_verdict.complete: true`, `unresolved: []` | no (happy path) |
| `test_verdict_unanswered_pq` | fixture: 1 PQ with no citing fact | `complete: false`, PQ id in `unresolved` | yes |
| `test_verdict_pq_cited_but_only_proven_initial` | fixture: PQ cited by PROVEN-INITIAL (not FULL) | `complete: false` (mirrors C0a — INITIAL does not close a PQ) | yes |
| `test_verdict_contradiction_detected` | fixture: 2 PROVEN facts same topic, no supersedes link | `contradictions` non-empty | yes |
| `test_verdict_model_selection_pq_c0b` | fixture: `need: model_selection`, 1 PROVEN + rest REFUTED | `complete: true` for that PQ | yes (mirrors C0b) |
| `test_no_cti_agent_in_manifest` | `release-manifest.yaml` contents | no `cti-correlator.md`/`shodan-host.md` entries | regression guard |
| `test_no_cti_agent_file_exists` | `agents/` directory listing | `cti-correlator.md`/`shodan-host.md` absent | regression guard |
| `test_skill_no_cti_specialist_mention` | `SKILL.md` contents | no `cti-correlator`/`shodan-host` substring | regression guard |

### Edge Cases Checklist
- [x] Empty `primary_questions[]` — verdict should report `complete: true` trivially (no
  questions to answer) but flag it in `self_audit.open_questions` as a task_spec smell
  (mirrors #77's concern about empty-ID-set silently meaning "nothing to check" — do not
  let empty PQs silently mean "converged," make it explicit in self_audit).
- [x] PQ cited by a fact that itself got superseded after verdict wrote its file — stale
  verdict; out of scope for this batch (verdict is point-in-time, re-run on demand, same
  as today).
- [x] Two competing hypotheses in a `model_selection` PQ both still OPEN — verdict must
  report `complete: false` for that PQ, not silently pick one.
- [x] Concurrent access — N/A, verdict-scorer is a single Read+Write-once agent invocation,
  no concurrency concern introduced by this change.
- [x] Network failure — N/A, no network calls remain in verdict-scorer after attribution/
  CTI removal (this is itself a nice side effect — verdict-scorer becomes pure-local).
- [x] Permission denied — unchanged from today (Read/Write on local workspace files only).

---

## Validation Commands

### Static Analysis
```bash
cd "C:/Users/hr/.claude/kunglao-remote-dev"
python -m py_compile scripts/*.py hooks/*.py
```
EXPECT: Zero syntax errors (only relevant if Task 9 adds a new `scripts/verdict_*.py`
validator; if verdict stays pure-agent-prompt with only a JSON Schema file, this step is
a no-op check that nothing else broke).

### Unit Tests
```bash
cd "C:/Users/hr/.claude/kunglao-remote-dev"
python -m pytest tests/test_verdict_contract.py tests/test_release_receipt.py tests/test_global_rule_subset.py -v
```
EXPECT: All new + updated tests pass.

### Full Test Suite
```bash
cd "C:/Users/hr/.claude/kunglao-remote-dev"
python -m pytest -q
```
EXPECT: Same pass count as current baseline + N new tests; the 2 known pre-existing
failures (`test_acceptance_overall_passes`, `test_contract_docs::test_skill_lte_500_lines`)
remain the ONLY failures — no new regressions, no new failures introduced by this batch.

### Schema Validation (if Task 9 adds `schemas/verdict-output.json`)
```bash
python -c "import json, jsonschema; jsonschema.Draft7Validator.check_schema(json.load(open('schemas/verdict-output.json')))"
```
EXPECT: No exception (schema itself is well-formed).

### OpenSpec Validation
```bash
npx --yes openspec validate reposition-re-only-scope
```
EXPECT: RC=0 (per the project's established `npx --yes openspec` workaround for the
broken global npm shim, documented in master-plan.md rev 25).

### Repo-wide Sweep (final gate, run once after all tasks land)
```bash
grep -rln "cti-correlator\|shodan-host" --include="*.md" --include="*.py" --include="*.yaml" . \
  | grep -v ".venv\|openspec/changes/release-contract\|openspec/changes/icd203-source-reliability"
```
EXPECT: Empty output.

```bash
grep -c "maliciousness\|attribution\|Admiralty\|Diamond\|\bACH\b\|classification\|named_actor" agents/verdict-scorer.md agents/verdict-redteam.md
```
EXPECT: `0` for both files.

### Manual Validation
- [ ] Read the rewritten `agents/verdict-scorer.md` end-to-end — confirm no residual
  malice/attribution vocabulary in prose (not just the grepped keywords — check for
  paraphrases like "threat actor" or "APT" without the exact grepped tokens).
- [ ] Confirm `SKILL.md` line count did not cross further above 560 (ideally trends
  toward 500, since text was net-removed).
- [ ] Confirm `task_spec.yaml` still validates against whatever schema/consumer reads it
  (`scripts/kunglao_record.py` Phase 0.4 intake) after the `external_cti_query` key
  removal — no KeyError on a fixture missing that key.

---

## Acceptance Criteria
- [ ] All 10 tasks completed
- [ ] All validation commands pass
- [ ] New tests written and passing (Task 9)
- [ ] No type errors / syntax errors in any touched `.py` file
- [ ] Zero live-contract references to `cti-correlator`/`shodan-host`/`maliciousness`/
  `attribution`/`Admiralty`/`Diamond`/`ACH`/`classification`/`named_actor` outside frozen
  historical openspec-change artifacts
- [ ] `verdict.json` schema is `analysis_verdict`-shaped and schema-guarded against the
  old shape resurfacing

## Completion Checklist
- [ ] Code/docs follow discovered patterns (AGENT_FRONTMATTER, DISPATCH_TABLE_ROW,
  OUTPUT_JSON_SCHEMA, CONSTRAINT_ENUM, TEST_STRUCTURE)
- [ ] Error handling matches project style (fail-closed / `degraded[]` self-honesty,
  mirrors #78's philosophy)
- [ ] Tests follow project test patterns (RED→GREEN, openspec-change-in-PR, one issue one
  PR one branch one worktree named `kunglao-agent`)
- [ ] No hardcoded values introduced
- [ ] `master-plan.md` delta log updated with a new revision entry after ship
- [ ] No unnecessary scope additions — firmware/game/CTI-replacement NOT added anywhere
- [ ] Self-contained — no questions needed during implementation

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| A script (hook/CLI) has a hardcoded literal reference to `external_cti_query`, `classification`, or `attribution` field names beyond the agent-prompt docs | Medium | Breaks a currently-passing test or silently no-ops a check | Task 6/9 GOTCHAs explicitly call for a repo-wide grep of `scripts/`+`hooks/` before deleting, not just doc files |
| SKILL.md line count grows past the current 560 (worsening the known >500 pre-existing failure) | Low-Medium | Cosmetic — test already fails, but shouldn't get further from green | Task 4 GOTCHA requires net-neutral-or-negative line delta; trim adjacent prose in the same edit if needed |
| `agents/kunglao-worker.md` or `agents/go-symbols.md` has a load-bearing routing instruction to cti-correlator that isn't just prose | Low | A worker would try to hand off to a deleted agent at runtime | Task 1 GOTCHA calls this out explicitly for inspection before finalizing the deletion |
| Test file audit (Task 9) misses a test that soft-asserts on old verdict fields via a loose dict `.get()` check that silently passes either way | Low | A regression ships undetected | Task 9's explicit RED-test list (schema-rejection tests) catches this structurally, not just via grep |

## Notes

This plan implements the user's explicit boundary correction from this session: "情报阶段
跟kunglao-agent没有关系，它只管完成逆向" (the intelligence phase has nothing to do with
kunglao-agent — it only handles completing the reverse engineering) and the earlier
correction "verdict本来就不需要做恶意判断。只需要验证分析结果对不对...逆向分析师包含
malware分析的所以这种思路师错的" (verdict never needed a maliciousness judgment — it
only needs to verify whether the analysis results are correct; RE includes malware
analysis as a subset, so removing malware-analysis capability entirely would have been
the wrong move — only the CTI/attribution *layer* is removed, not RE-of-malware itself).

This batch is independent of and can ship before/after/in-parallel with the previously
discussed structural cleanup (SKILL.md progressive-disclosure rewrite, absolute-path
relativization, dead-code gate wiring, re-library ctf-skills absorption) — those remain
separate future batches per `absorption-research-round2.md` P0-P4 priorities, now scoped
to explicitly exclude any CTI/firmware/game content per this same boundary correction.

## Next Steps

File Tasks 1-9 as GitHub issues (batch 4, one issue per task, tier `B4-P0` since this is
a correctness-of-contract fix, not a feature), each executed in its own
`wtNN/kunglao-agent` worktree per the project's `<=5 parallel isolated subagents`
constraint. Task 10 (final sweep + openspec + master-plan.md delta log) runs last, after
all others merge to `dev`.
