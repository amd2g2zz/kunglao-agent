## ADDED Requirements

### Requirement: One capability report per eval sample

The report SHALL join, for a single sample, the faces that answer what it got
and what it cost: facts counted by status, accuracy against the unit's ground
truth, orchestrator and worker token accounts, wall clock, dispatch count and
human interventions. Each face SHALL name the organ it was read from
(`source`), and the whole report SHALL be produced for any unit of the eval
set — a face that cannot be measured does not prevent the others from being
reported.

#### Scenario: A results document with several rows

- **WHEN** the report is generated from an eval-results document
- **THEN** one report file is written per row that names a workspace, plus a
  summary, and the exit status is 0

#### Scenario: A single workspace

- **WHEN** the report is generated for one workspace path
- **THEN** one report file is written with the same faces, the unit id taken
  from `--task` when given

#### Scenario: Nothing to report on

- **WHEN** the call carries neither a results document nor a workspace, or
  the results document cannot be read, or none of its rows name a workspace
- **THEN** the run is refused with exit status 2 and the reason on stderr, and
  no report is written

### Requirement: An absent organ is reported absent, never as zero

A face whose organ does not exist SHALL report a null value and a reason. An
organ that exists and reports zero SHALL be distinguishable from one that was
never read.

#### Scenario: No mission ledger

- **WHEN** a sample has no row-level dispatch metric and its workspace has no
  `runs/mission_ledger.yaml`
- **THEN** `dispatch.dispatch_count` is null with a reason naming the unmeasured
  organ, and the dispatch ledger's row count is reported separately

#### Scenario: No transcript

- **WHEN** a sample has no locatable session transcript
- **THEN** the orchestrator and worker token accounts are null with a reason,
  and no dollar figure is derived

#### Scenario: No verdict

- **WHEN** a sample's row carries no checker verdict
- **THEN** `accuracy.verdict` and `accuracy.correct` are null with a reason,
  and the sample is not counted as a failure

### Requirement: Accuracy uses the control arm's definitions

Accuracy against `ground_truth.json` SHALL be computed with
`eval_control_arm`'s own metric definitions — its answer set, its
`is_false_proven` / `is_premature_closure` predicates and its rate functions —
so a per-sample face and a campaign readout cannot drift apart. The
claimed-closure bit SHALL be read where the control arm reads it (the checker's
`metrics.converged`), and the falsification legs SHALL run only when a regrade
is explicitly requested.

#### Scenario: A passing sample

- **WHEN** a row is PASS and carries an evidence reference
- **THEN** it counts as answered, correct and proven-with-evidence

#### Scenario: SKIP and REFUSED rows

- **WHEN** a row's verdict is SKIP or REFUSED
- **THEN** it is answered=false and correct=false, because an ungradeable run
  is not an answer

#### Scenario: The legs were not run

- **WHEN** a sample is graded without a regrade request
- **THEN** the minted-probe and re-run values stay null, the face says the legs
  were not requested, and neither false-proven nor premature-closure is
  asserted

#### Scenario: Batch rates match the control arm

- **WHEN** the same rows are graded by `eval_control_arm.arm_metrics` and
  aggregated from per-sample reports
- **THEN** the answer rate, proven-with-evidence rate, premature-closure rate
  and false-proven rate are equal

### Requirement: Corpus content never travels

The ground-truth face SHALL name the unit and state whether its
`ground_truth.json` exists. It SHALL NOT copy a value out of that file into any
report or summary.

#### Scenario: A resolvable unit

- **WHEN** the unit resolves inside the corpus root and carries ground truth
- **THEN** the face records the task directory and `present: true`, and no
  constant from the ground truth appears anywhere in the report

#### Scenario: A unit absent from the corpus

- **WHEN** the unit cannot be resolved in the corpus root
- **THEN** `present` is false with a reason, and no accuracy is invented

### Requirement: Facts are counted from the sanctioned status organ

The fact count SHALL come from `facts/_INDEX.md` through the single-source
index parser when that organ exists, and otherwise from the fact files' own
frontmatter. The index file itself SHALL NOT be counted as a fact, and a
disagreement between the index and the files present SHALL be reported.

#### Scenario: An index exists

- **WHEN** the workspace carries a `facts/_INDEX.md`
- **THEN** the counts come from the index organ, the file count is reported
  beside them, and a stale index shows up as a non-zero delta

#### Scenario: No index

- **WHEN** the workspace has fact files but no index
- **THEN** the counts come from frontmatter, a fact with a blank or missing
  status counts as UNKNOWN, and an unreadable file counts as UNREADABLE

### Requirement: Token accounts stay split and unpriced

The token face SHALL keep the orchestrator and worker populations apart, SHALL
prefer the usage face harvested at run time over a second fold of the same
transcript, and SHALL NOT derive a dollar figure from token counts.

#### Scenario: A session that dispatched workers

- **WHEN** the sample's session has worker transcripts
- **THEN** the orchestrator and worker token sums are reported in separate
  fields, with the worker file count beside them

#### Scenario: The run recorded its own face

- **WHEN** the row's `session_cost` carries a harvested usage face
- **THEN** that face is reported and the transcript is not re-folded, and the
  source says so

#### Scenario: A session killed before it reported

- **WHEN** the transcript carries usage rows but no cost-state row
- **THEN** the token account is reported, `total_cost_usd` stays null, and no
  price is computed from the tokens

### Requirement: The cockpit ratio face rides the report

The report SHALL carry the workspace's `runs/.cockpit-ratio.json` exactly as the
capture hook wrote it, including its timestamp, so the harness-to-analysis
ratio has a consumer that does not depend on any single process reading it.

#### Scenario: The hook sampled the workspace

- **WHEN** the workspace carries a ratio face
- **THEN** the report carries its ratio, token counts, worker-transcript count
  and alarm flag unchanged

#### Scenario: The hook never sampled it

- **WHEN** the workspace has no ratio face
- **THEN** the report says so with a reason, and reports no ratio

### Requirement: The cross-arm cost denominator is the declared token unit

The report SHALL express a sample's cost in `bench_tokens.grand_total`
(input + output + cache-read + cache-creation) summed **per population and then
added across populations**, so a session that dispatched workers is not
undercounted by the single-file view of that unit. Dollar figures SHALL remain a
secondary face that exists only where the CLI itself reported them, SHALL carry
their coverage share, and SHALL NEVER be interpolated from token counts.

#### Scenario: A session with worker transcripts

- **WHEN** the sample's session ran workers
- **THEN** `tokens.grand_total` reports the orchestrator total, the worker total
  and their sum, and the per-solution denominator uses the sum

#### Scenario: A worker-free session

- **WHEN** the session has no worker transcripts
- **THEN** the reported session total equals `bench_tokens.collect()` on the same
  transcript, so the two faces of the declared unit cannot drift

#### Scenario: A killed session with no dollar figure

- **WHEN** a sample has token rows but the CLI never wrote a cost row
- **THEN** the token denominator is still reported, `total_cost_usd` stays null,
  and the batch summary records the dollar subset's coverage instead of filling
  the gap

#### Scenario: A batch where no sample was solved

- **WHEN** no sample in the batch is correct
- **THEN** `cost_per_correct_solution_tokens` is null rather than zero, and the
  covered-sample counts are reported
