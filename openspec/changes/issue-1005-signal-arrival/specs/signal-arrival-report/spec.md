## ADDED Requirements

### Requirement: Read-only signal-arrival report

The system SHALL provide `scripts/rlvr/signal_arrival.py <workspace>`, a report over one workspace that prints exactly one JSON object (schema `signal-arrival/1`) on stdout and exits 0 whenever a report is printed — including when every count is `no data`. The report SHALL import only the standard library and SHALL open nothing for writing: no ledger, no lock file, no append-mode open.

#### Scenario: Workspace left untouched

- **WHEN** the report runs on a workspace, from any working directory, with malformed lines and missing sources among its files
- **THEN** every file keeps its content and its modification time, every directory (the workspace root included) keeps its modification time, no file or directory appears, and none disappears

#### Scenario: Empty directory left untouched

- **WHEN** the report runs on an existing empty directory
- **THEN** the directory is still empty afterwards and the exit code is 0

#### Scenario: Path that is not a directory

- **WHEN** the workspace argument does not name an existing directory
- **THEN** nothing is printed on stdout and the exit code is 64

#### Scenario: Command prints the seven counts

- **WHEN** the report runs on a workspace with recorded rows
- **THEN** stdout is one JSON object whose `counts` holds exactly `candidate_families`, `dispatch_decisions`, `settlement`, `credit_rows`, `posterior`, `hypothesis_resolution_rows` and `method_lead`, in this order

### Requirement: A leaf is a number or an explicit no-data

Each count SHALL be made of leaves. A leaf's `value` SHALL be a number (or a mapping, for a per-id or per-action breakdown) or the string `no data`, and a `no data` leaf SHALL carry a `reason` naming the source that is missing, empty or unparsable.

#### Scenario: Empty workspace

- **WHEN** the workspace is an existing directory with no files
- **THEN** every leaf of every count is `no data` with a reason and the exit code is 0

#### Scenario: A missing source beside a present one

- **WHEN** one source of a count is not on disk while the others are
- **THEN** the leaves that depend on the missing source are `no data` naming it, and the leaves whose sources are present keep their numbers

#### Scenario: A ledger of malformed lines only

- **WHEN** every line of `runs/experience.jsonl` is malformed
- **THEN** the counts read from that ledger are `no data` with an `unparsable` reason

### Requirement: No blank field under a count

No field under `counts` SHALL be null, an empty string or an empty list.

#### Scenario: Populated workspace

- **WHEN** the report runs on a workspace with recorded rows
- **THEN** no field under `counts` is null, an empty string or an empty list

### Requirement: Zero is a fact about a source that exists

A count of 0 over a source that exists SHALL be reported as 0, never as `no data`.

#### Scenario: Zero rows in a ledger that exists

- **WHEN** `runs/experience.jsonl` is readable and holds no `hypothesis-resolution/1` row
- **THEN** `hypothesis_resolution_rows` is 0

#### Scenario: No credit row booked

- **WHEN** the ledger holds dispatch rows and no credit row
- **THEN** `credit_rows.booked` is 0 and `by_dispatch_id` is an empty mapping

### Requirement: A malformed ledger line is reported, not fatal

The report SHALL count the valid rows of a damaged ledger and state, for each file, how many of its lines are malformed.

#### Scenario: A malformed ledger line

- **WHEN** `runs/experience.jsonl` holds a line that is not JSON beside valid rows
- **THEN** the report exits 0, counts the valid rows, and states one malformed line for that file

#### Scenario: JSON nested past what the decoder can read

- **WHEN** a line of `runs/experience.jsonl`, or a JSON document the report reads, is valid JSON nested deeper than the decoder can go
- **THEN** the report exits 0, counts the line as malformed, and the leaves read from that file are `no data` with an `unparsable` reason

### Requirement: The counts read what is durable

Each count SHALL be computed from the files the production writers leave, and the report SHALL state where a count has no durable trace of its own.

#### Scenario: Candidates at the first dispatch

- **WHEN** the first `q-cell-obs/1` dispatch row in `runs/experience.jsonl` carries a `candidates` mapping
- **THEN** `candidate_families.first_dispatch` is the number of candidates and names the families and the source

#### Scenario: First dispatch without a recorded receipt

- **WHEN** the first dispatch row carries no `candidates` column
- **THEN** `first_dispatch` is `no data` saying the row carries no sampling receipt, and `llm_prior` is counted on its own from `runs/llm-prior.json`

#### Scenario: No dispatch row reached the ledger

- **WHEN** the ledger holds no dispatch row and `runs/.dispatch-decisions` holds staged receipts
- **THEN** `first_dispatch` is the candidate count of the earliest staged receipt and names that source

#### Scenario: Staged receipts and ledger rows are counted apart

- **WHEN** `runs/.dispatch-decisions` holds staged decision receipts and `<id>.credit.json` deferred credit files
- **THEN** `staged_receipts` counts the decision receipts only, `deferred_credit_files` counts the deferred credit files only, and `ledger_dispatch_rows` counts the dispatch rows of the ledger

#### Scenario: Dispatch id the dispatch ledger does not carry

- **WHEN** a ledger dispatch row's `dispatch_id` is not carried by any row of `runs/dispatch-ledger.jsonl`
- **THEN** that row is not counted in `rows_reachable_by_dispatch_id`

#### Scenario: Dispatch id of another JSON type

- **WHEN** a ledger dispatch row's `dispatch_id` is a JSON list or object
- **THEN** the report exits 0, counts that row in `ledger_dispatch_rows` and in `rows_without_dispatch_id`, and not in `rows_reachable_by_dispatch_id`

#### Scenario: Unmatched settlement

- **WHEN** a settlement found no pending dispatch row and its warn row is in `runs/logs/kunglao-*.jsonl`
- **THEN** `settlement.unmatched` counts those warn rows, lists their dispatch ids (an empty id by a word), and does not count the same warning from any other face; `settlement.attempts` is the settlement rows `q_cells.observe_settlement` booked plus those warn rows

#### Scenario: Credit rows that are not settlement attempts

- **WHEN** the ledger holds credit rows that no call of `q_cells.observe_settlement` wrote — an amendment, a step bank, a calibration bank
- **THEN** `settlement.other_credit_rows` counts them per face, none of them is in `settlement.banked` or in `settlement.attempts`, and `credit_rows.booked` still counts every credit row

#### Scenario: The unmatched trace is not on disk

- **WHEN** `runs/logs` is missing while credit rows are booked
- **THEN** `settlement.unmatched` and `settlement.attempts` are `no data` naming the run log, and `settlement.banked` keeps its number

#### Scenario: Credit rows by dispatch id

- **WHEN** credit rows are booked under dispatch ids
- **THEN** `credit_rows.booked` is their number, `by_dispatch_id` counts them per id, and the ids no dispatch row carries are listed under `ids_without_dispatch_row`

#### Scenario: Posterior first versus last

- **WHEN** `runs/plan-receipts.jsonl` records at least two decisions with posterior cells
- **THEN** `posterior.before` and `posterior.after` are the cells of the first and the last recorded decision, `coverage` is `first-vs-last`, and `moved` says whether they differ

#### Scenario: Only the current posterior state exists

- **WHEN** one decision is recorded, or only the projection `runs/policy-state.json` exists
- **THEN** `coverage` is `current-state-only`, `source` names the file read, and `before` equals `after`

#### Scenario: Hypothesis-resolution rows

- **WHEN** `runs/experience.jsonl` holds `hypothesis-resolution/1` rows
- **THEN** `hypothesis_resolution_rows` equals the `experience:hypothesis-resolution/1` count of `consolidated_ledger.liveness` over the same workspace

#### Scenario: Method lead in the strategy seam

- **WHEN** `runs/round-strategy.json` carries a section titled `dispatch-lead`
- **THEN** `method_lead` is 1 and names the lead family

#### Scenario: Strategy seam without a lead

- **WHEN** `runs/round-strategy.json` is a `round-strategy/1` object whose sections carry no `dispatch-lead`
- **THEN** `method_lead` is 0

### Requirement: The report names the build the workspace ran on

The report SHALL carry the workspace's init skill version and the distinct `version` stamps of its run-log rows, so numbers read off an old workspace are not taken for results at a pinned tip. Each of the two labels SHALL be a leaf: the value, or `no data` with the reason beside it.

#### Scenario: Run log carries several versions

- **WHEN** run-log rows carry several `version` stamps
- **THEN** the report lists each stamp with its row count, the first and the last seen, and the init report's skill version when `runs/.init-report.json` exists

#### Scenario: No build label on disk

- **WHEN** `runs/.init-report.json` and `runs/logs` are missing
- **THEN** each label of `workspace_build` is `no data` and carries the reason naming the missing source
