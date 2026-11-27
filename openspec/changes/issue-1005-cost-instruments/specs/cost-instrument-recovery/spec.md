## ADDED Requirements

### Requirement: Worker output tokens are counted from the session's worker transcripts

The cockpit-ratio gauge SHALL compute its analysis side over a whole
session — the transcript the hook is handed plus the worker transcripts
written beside it under `<session>/subagents/agent-*.jsonl` — and SHALL
count only sidechain rows' output tokens into it, so that a session which
dispatched workers reports a non-zero analysis side.

#### Scenario: Real session whose workers ran

- **WHEN** the gauge folds a session whose main transcript carries no
  sidechain row and whose worker files do
- **THEN** `analysis_output_tokens` is the sum of the worker files'
  sidechain output tokens and is greater than zero, and `ratio` is
  `machine_input_tokens / analysis_output_tokens` rather than
  `machine_input_tokens / 1`

#### Scenario: Session that dispatched no worker

- **WHEN** the session has no `subagents` directory beside its transcript
- **THEN** the fold reports exactly the numbers the main transcript alone
  supports, with zero worker files seen

#### Scenario: Machine side keeps its scope

- **WHEN** worker transcripts carry input or cache-read tokens
- **THEN** they are not added to `machine_input_tokens`, which stays the
  orchestrator rows' input including cache reads

#### Scenario: Sidechain rows inlined in the main transcript

- **WHEN** a harness writes the worker rows into the main transcript itself
- **THEN** those rows count into the analysis side as they always did

### Requirement: Reading a worker transcript fails visibly, never silently

A worker transcript that cannot be read SHALL cost only its own
contribution: the sample is still written, the loss is counted in the face,
and a malformed line inside a readable file is skipped.

#### Scenario: Unreadable worker transcript

- **WHEN** a path matching the worker-file shape cannot be read
- **THEN** the ratio face is still produced, its `analysis_output_tokens`
  holds what the readable files carry, `worker_unread` counts the loss and
  `worker_transcripts` counts every file seen

#### Scenario: Torn or malformed line

- **WHEN** a worker transcript contains a line that is not valid JSON
- **THEN** the line is skipped and the remaining rows of that file are
  counted

### Requirement: The worker memo is a pure memo

The per-call memo SHALL never change a reported number: a memoized sample
and a fresh fold agree, a file that grew is re-folded, and a corrupt or
missing memo recomputes from disk.

#### Scenario: Repeat sample over an unchanged session

- **WHEN** the gauge samples the same session twice with the memo in place
- **THEN** both samples report the same analysis and machine totals

#### Scenario: Worker transcript grows between samples

- **WHEN** rows are appended to a worker transcript and the gauge samples
  again
- **THEN** the new total includes the appended rows

#### Scenario: Memo unreadable

- **WHEN** the memo file is absent or contains unparsable content
- **THEN** the sample still reports the exact totals of a fresh fold

### Requirement: A session that never reported its cost still reports its consumption

The eval loop SHALL read a session's consumption off its transcript when
the session's own stdout report did not arrive: the CLI's cumulative cost
row when the session wrote one, the usage rows' token account always, and an
explicit reason when no dollar figure exists. It SHALL NOT derive a dollar
figure from token counts.

#### Scenario: Wall-cap killed session whose CLI flushed its cost row

- **WHEN** a session is killed past its wall cap, writes no stdout report,
  and its transcript carries a cost-state row
- **THEN** `session_cost.total_cost_usd` is that row's number,
  `cost_source` is `transcript-cost-state`, and the token account is
  reported under `transcript_usage`

#### Scenario: Wall-cap killed session whose CLI never flushed a cost row

- **WHEN** the transcript carries usage rows but no cost-state row
- **THEN** `total_cost_usd` stays null, `cost_source` is
  `transcript-usage-tokens`, and `cost_unavailable_reason` names the missing
  cost-state row — while the orchestrator and worker token sums are still
  booked

#### Scenario: Transcript belongs to another workspace

- **WHEN** the newest transcript in the workspace's directory names a
  different cwd in its own rows, or was written before the launch
- **THEN** it is not used, and no other run's spend is reported for this one

#### Scenario: Nothing on disk for this session

- **WHEN** no qualifying transcript exists for the workspace and window
- **THEN** the session's cost face keeps the shape it had before this change
  (absent), and no zero is invented

### Requirement: The cost face states its own provenance

Every `session_cost` the eval loop reports SHALL say where its number came
from, so an account that mixes sources is visible on the data itself.

#### Scenario: CLI report arrives

- **WHEN** the session's own stdout result carries a cost figure
- **THEN** that figure is used, `cost_source` is `cli-result`, and the
  transcript is not read for cost

#### Scenario: Mixed account

- **WHEN** a results document contains rows with different `cost_source`
  values
- **THEN** each row still names its own source, and the token account is
  present on every row that harvested one
