## ADDED Requirements

### Requirement: external-checker verification verdicts SHALL be captured as independent OUTCOME ledger rows

`scripts/outcome_capture.py::capture(workspace)` SHALL scan `runs/*.md`, identify verify-note files (name contains `-verify-`, carrying an `## Overall verdict` section with value `passes`/`partial`/`fails`) and red-team files (name contains `verify-redteam`, carrying a `RED-TEAM VERDICT: CONFIRMED|REFUTED|UNVERIFIED(-WITH-GAP)` line), and append each result as an independent row `{"type":"outcome","ts","claim_id","result","checker"}` to `.convergence_ledger.jsonl`. The row type SHALL be the already-frozen `status_defs.LedgerLineType.OUTCOME` (no new constant). `claim_id` SHALL be read from note frontmatter (`claim_id:`) for verify-note and from body (`claim:/target:` → `C-NNN`) for red-team, falling back to the filename when absent. Capture SHALL be idempotent: a row whose `claim_id|checker|result` key already exists in the ledger SHALL NOT be appended twice (mirroring `kunglao_record.record_event` idempotency, excluding the volatile `ts`). Missing `runs/`, unreadable files, files without a verdict section, and malformed JSON lines in the ledger SHALL be skipped without crashing.

#### Scenario: verify-note passes is captured as one OUTCOME row
- **WHEN** `runs/2026-08-11T00-00-00-verify-01-draft.md` contains `## Overall verdict\npasses\n`
- **THEN** `capture` appends exactly one row with `type=="outcome"`, `result=="passes"`, `checker=="verify-note"`, and returns 1

#### Scenario: red-team CONFIRMED is captured
- **WHEN** `runs/verify-redteam-C-7.md` contains `RED-TEAM VERDICT: CONFIRMED` and body `claim: C-7`
- **THEN** `capture` appends one row with `result=="CONFIRMED"`, `checker=="red-team"`, `claim_id=="C-7"`

#### Scenario: duplicate verify is not double-counted
- **WHEN** two verify files resolve to the same `claim_id|checker|result` key AND `capture` is called twice
- **THEN** the ledger holds exactly one OUTCOME row for that key (idempotent)

#### Scenario: missing runs/ or malformed ledger lines do not crash
- **WHEN** `runs/` is absent OR the ledger contains empty/JSON-invalid lines
- **THEN** `capture` returns 0 (no crash) and `read_outcome_rows` skips the bad lines

### Requirement: `aggregate_reward` SHALL be a pure function mapping outcome results to a scalar, returning None when there is no outcome data

`aggregate_reward(rows) -> float | None` SHALL map outcome results to scores (`passes`/`CONFIRMED` = 1.0, `partial`/`UNVERIFIED`/`UNVERIFIED-WITH-GAP` = 0.5, `fails`/`REFUTED` = 0.0, unknown result = 0.0), average over rows whose `type == LedgerLineType.OUTCOME`, and return `None` when there are zero outcome rows. The function SHALL be pure (same input → same output, no side effects, no LLM calls) and SHALL ignore SNAPSHOT rows even when passed the full ledger.

#### Scenario: mixed results average correctly
- **WHEN** rows are `[{C-1,passes,verify-note},{C-2,partial,verify-note},{C-3,fails,verify-note},{C-4,CONFIRMED,red-team}]`
- **THEN** `aggregate_reward` returns `(1.0 + 0.5 + 0.0 + 1.0) / 4 == 0.625`

#### Scenario: no outcome data returns None (neutral, not 0.0)
- **WHEN** `aggregate_reward([])` is called
- **THEN** the result is `None` (distinguishing "no signal" from "all-fails")

#### Scenario: snapshot rows are ignored by aggregation
- **WHEN** the ledger carries only SNAPSHOT rows (no `type` field)
- **THEN** `read_outcome_rows` returns `[]` and `aggregate_reward` returns `None`

### Requirement: the reward signal SHALL NOT gate any mechanical convergence or dispatch gate

The reward scalar is a SOFT signal only — intended as a future priority factor / prompt-injection hint. `outcome_capture` SHALL NOT modify `priority.py`, `convergence_check.py`, or any hook. Wiring the reward into a decision is explicitly deferred to a later change (pending ≥2 samples to avoid overfitting).

#### Scenario: reward is observable but non-gating
- **WHEN** the orchestrator runs `outcome_capture.py <workspace> --reward`
- **THEN** the reward scalar is printed for observation but no convergence/dispatch decision is altered by it
