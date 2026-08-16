## ADDED Requirements

### Requirement: `failure_analysis_gate --record` SHALL accept optional `--outcome` and `--what-happened`, writing them into the analysis entry without breaking existing parse

`scripts/failure_analysis_gate.py::record_analysis` SHALL accept two new optional arguments `outcome` and `what_happened`, and include them as optional fields `outcome` and `what_happened` in the `analyses/failure-<claim_id>.yaml` entry. `outcome` SHALL be one of `PROVEN|VERIFIED|REFUTED|NEGATIVE` (normalized to uppercase; rejected otherwise with a machine-readable reason); `--outcome` and `--what-happened` SHALL be provided together or not at all (mismatched usage SHALL be rejected). When an existing analysis entry is present and the caller does not re-supply `--assumption`/`--validity`/`--next-method`, the recorded entry SHALL preserve the prior values of `method_assumption`, `assumption_validity`, `next_method` and `analyzed_at` (closure-time recording must not clobber the failure-time analysis). Entries without `outcome` SHALL remain fully parseable: `_analysis_covers`, `scan_workspace`, `convergence_check._failure_blocked`, `priority` and `hooks/dispatch_gate._failure_blocked_ids` SHALL keep behaving identically for old and new entry files (backward compatibility, no migration).

#### Scenario: recording an outcome at claim closure writes both new fields
- **WHEN** a claim C-1 with `promotion_attempts: 3` has an existing analysis entry `{method_assumption: "grep sees IOCs", assumption_validity: "not-justified", next_method: "runtime Frida hook", analyzed_at: "2026-08-10T00:00:00Z"}` and the orchestrator records `--record C-1 --outcome PROVEN --what-happened "Frida caught NtCreateThreadEx"` with no other flags
- **THEN** the rewritten entry contains `outcome: PROVEN` and `what_happened: "Frida caught NtCreateThreadEx"`, and still contains the original `method_assumption`, `assumption_validity`, `next_method` and `analyzed_at` values

#### Scenario: invalid or mismatched outcome usage is rejected
- **WHEN** recording with `--outcome MAYBE` OR `--outcome PROVEN` without `--what-happened` OR `--what-happened "x"` without `--outcome`
- **THEN** `record_analysis` returns `{"recorded": False, "reason": ...}` and no analysis file is written

#### Scenario: old-style record without outcome stays byte-compatible
- **WHEN** recording with only `--assumption`/`--validity`/`--next-method` (pre-#41 style)
- **THEN** the entry has exactly the legacy field set (`claim`, `covers_attempt`, `method_assumption`, `assumption_validity`, `next_method`, `analyzed_at`) and `scan_workspace` still reports the claim BLOCKED/OK exactly as before

### Requirement: the `--lessons` aggregation mode SHALL emit `lessons/lesson-*.md` grouped by failure signature, closed-loop outcomes only

A new CLI mode `--lessons` SHALL scan every `analyses/failure-*.yaml` in the workspace, group entries by failure signature `(method_assumption, next_method, claim_topic)` where `claim_topic` is the claim's `topic` field or its normalized statement (fallback `claim_id`), and write one `lesson-<slug>.md` per signature into the lessons library directory (default `~/.claude/skills/kunglao-agent/references/lessons/`, overridable with `--library`). `slug` SHALL be the first 10 hex chars of `sha256(<signature normalized string>)`, so the same signature maps to the same filename and re-running aggregation SHALL be idempotent (existing files are skipped, never overwritten). A lesson file SHALL list every closed-loop source claim of its signature group with its `outcome` and `what_happened` text. Only closed-loop entries enter the library: `outcome in {PROVEN, VERIFIED}` unconditionally, and `outcome == NEGATIVE` only when the ledger `.convergence_ledger.jsonl` carries an OUTCOME row `{claim_id, checker: "red-team", result: "CONFIRMED"}` (read via `outcome_capture.read_outcome_rows`, pure read). All other entries — `REFUTED`, `NEGATIVE` without the red-team row, and entries with no `outcome` — SHALL NOT produce lesson files; they SHALL be appended to the /reflect human queue file (default `~/.claude/learnings-queue.json`, overridable with `--reflect-queue`) as JSON-array items `{type: "failure-lesson-candidate", message, timestamp, project, claim_id, outcome, reason, next_method, method_assumption}` where `reason` is `refuted`, `negative-unverified`, or `no-outcome`; an item with the same `claim_id|reason` SHALL NOT be appended twice. Missing analyses dir, unreadable files, and claims absent from the register SHALL be handled without crashing.

#### Scenario: closing a PROVEN claim produces a lesson file by failure signature
- **WHEN** `analyses/failure-C-1.yaml` has `{method_assumption: "A", next_method: "M", outcome: PROVEN, what_happened: "worked"}` and claim C-1 has statement "detect C2 protocol", and `--lessons --library <tmp>` is run
- **THEN** exactly one `lesson-*.md` appears in `<tmp>` whose frontmatter carries `method_assumption: A`, `next_method: M`, `claim_topic` derived from C-1's statement, `outcome: PROVEN` and whose body contains "worked", and the CLI reports 1 written

#### Scenario: NEGATIVE enters the library only when red-team CONFIRMED exists
- **WHEN** `analyses/failure-C-2.yaml` has `outcome: NEGATIVE` and `.convergence_ledger.jsonl` contains `{"type":"outcome","claim_id":"C-2","checker":"red-team","result":"CONFIRMED"}` (as produced by #35)
- **THEN** `--lessons` writes a lesson file for C-2's signature
- **AND WHEN** the same analysis exists but the ledger has no red-team row for C-2
- **THEN** no lesson file is written and a `/reflect` queue item with `claim_id: C-2` and `reason: negative-unverified` is appended

#### Scenario: REFUTED and no-outcome entries go to the /reflect queue, not the library
- **WHEN** `analyses/failure-C-3.yaml` has `outcome: REFUTED` and `analyses/failure-C-4.yaml` has no `outcome` field
- **THEN** no lesson file is written for either, the queue receives items with `reason: refuted` (C-3) and `reason: no-outcome` (C-4), and re-running `--lessons` appends no duplicate queue items

#### Scenario: same-signature claims group into one lesson file, idempotently
- **WHEN** C-5 and C-6 share identical `(method_assumption, next_method, claim_topic)` and both have closed-loop outcomes
- **THEN** one lesson file lists both C-5 and C-6 as sources, and running `--lessons` again writes no additional file and no additional queue item

### Requirement: BLOCKED output SHALL include up to 3 similar lessons retrieved by keyword overlap

`check_claim` SHALL, for a BLOCKED result, compute `similar_lessons`: score every lesson file in the library against the blocked claim's statement and claim_id by counting overlapping significant tokens (lowercase, `\w{3,}`) between the claim text and the lesson file text, and include the top 3 by descending score (tie-break: filename) as `{file, score, outcome, next_method, claim_topic}` entries — an empty or missing library yields `[]`. The BLOCKED human-readable output SHALL print the retrieved lessons. A `--search <keywords>` CLI mode SHALL print the same scoring result for arbitrary keywords. Retrieval SHALL be plain keyword/token matching (no embeddings, no external calls).

#### Scenario: BLOCKED output contains 3 similar lessons
- **WHEN** the library holds 5 lesson files whose `next_method`/`claim_topic` tokens overlap the blocked claim C-7's statement tokens, with the 3 best scores unambiguous
- **THEN** `check_claim` BLOCKED dict has exactly 3 `similar_lessons` entries, the best-scoring file first, and the human output prints them

#### Scenario: empty library yields no similar lessons
- **WHEN** the library directory does not exist or contains no lesson files
- **THEN** `similar_lessons` is `[]` and the BLOCKED decision, exit code and `_failure_blocked_ids` result are unchanged from pre-#41 behavior

#### Scenario: keyword search returns matching lessons without a workspace
- **WHEN** `--search "frida runtime" --library <tmp>` is run and one lesson's text contains "frida" and "runtime"
- **THEN** the CLI prints that lesson's file, topic and outcome; a query with no overlap prints an empty result and exits 0

### Requirement: the lessons library directory and reflect queue path SHALL be parameterized

The lessons library default SHALL be `<home>/.claude/skills/kunglao-agent/references/lessons/` (global, cross-sample — never per-workspace) and the reflect queue default SHALL be `<home>/.claude/learnings-queue.json`. Both SHALL be overridable via `--library` and `--reflect-queue` respectively, so tests exercise the feature entirely against tmp paths and never touch the production library or queue.

#### Scenario: tests never write to the production library
- **WHEN** tests run `--lessons --library <tmp>/lib --reflect-queue <tmp>/queue.json` (or the equivalent function arguments)
- **THEN** all lesson files and queue items land under `<tmp>`, and the default paths are only read by the production CLI paths (BLOCKED retrieval) and never written by test runs
