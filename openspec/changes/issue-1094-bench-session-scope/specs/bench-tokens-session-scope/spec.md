## ADDED Requirements

### Requirement: The experiment's cost unit is measured over the whole session

`bench_tokens.collect()` SHALL fold the session — the transcript it is
handed plus the worker transcripts beside it under
`<session>/subagents/agent-*.jsonl` — and its `grand_total` SHALL be the
sum of all four token faces over that whole session, so the declared
experiment cost unit carries the worker population of sessions that
dispatched workers.

#### Scenario: Session that dispatched workers

- **WHEN** the main transcript is folded together with the worker
  transcripts beside it (the real on-disk layout)
- **THEN** the receipt's `grand_total` is strictly greater than the
  main transcript's single-file total, and `worker_transcripts` reports
  how many worker files were folded

#### Scenario: Session that dispatched no worker

- **WHEN** no `subagents` directory exists beside the transcript
- **THEN** the receipt equals the single-file fold in every field, with
  `worker_transcripts` zero

### Requirement: The session read domain is single-sourced

The file set "one session = the main transcript + its worker
transcripts" SHALL be enumerated by one shared implementation that every
reader of that domain imports; the bench meter and the cost-capture hook
SHALL NOT each carry their own enumeration.

#### Scenario: Shared enumeration

- **WHEN** either the bench meter or the cockpit-ratio fold needs the
  worker transcripts of a session
- **THEN** both obtain the list from the same shared function, and the
  hook's behaviour is unchanged by the move

### Requirement: Human turns are counted from the main transcript only

`user_turn_count` SHALL count genuine user turns in the main transcript
only; `type=user` rows inside worker transcripts are dispatch envelopes
and SHALL NOT count, so the human-intervention signal is not poisoned by
dispatches.

#### Scenario: Worker file carries user rows

- **WHEN** a worker transcript contains genuine-looking user rows
- **THEN** the receipt's `user_turn_count` is what the main transcript
  alone supports

### Requirement: Partial truth stays visible

A row without a usage face, or a worker transcript that cannot be read,
SHALL mark the receipt `usage_incomplete` and cost only its own
contribution; the receipt SHALL report `worker_unread` so the loss is
counted, never silently zero.

#### Scenario: Worker row without usage

- **WHEN** an assistant row inside a worker transcript carries no usage
- **THEN** `usage_incomplete` is true while the rows that do carry usage
  are still summed

#### Scenario: Unreadable worker transcript

- **WHEN** a worker file matching the glob cannot be read
- **THEN** the fold continues over the remaining files,
  `worker_unread` counts the loss, and `usage_incomplete` is true

### Requirement: The token sums are deterministic in input order

The token accumulation SHALL be in-order integer addition over a fixed
file order — the main transcript first, then the worker transcripts
sorted by name — and SHALL NOT be replaced by a reordered or pairwise
reduction.

#### Scenario: Order pin

- **WHEN** the same session is folded twice, or the receipt is compared
  against the per-file folds summed in the canonical order
- **THEN** the totals are identical, and the file order is
  main-first-then-sorted-workers

### Requirement: Wall clock spans the whole session

`wall_s` SHALL be the first→last timestamp span across ALL of the
session's transcripts, not the main file alone.

#### Scenario: Worker outlives the main transcript's last row

- **WHEN** a worker transcript's last row is timestamped after the main
  transcript's last row
- **THEN** `wall_s` includes that later row, and with no workers the
  span is the main transcript's own first→last span
