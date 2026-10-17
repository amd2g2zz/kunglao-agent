# blind-settlement-687 delta — issue-687-blind-settlement

## ADDED Requirements

### Requirement: The settler input is built from a whitelist, never from the producer's narrative

The settlement entry SHALL accept only inputs built by the blind
builder: raw step artifacts addressed workspace-relatively and hashed
(path + sha256), the claim/question the settlement targets, the
settlement rules table (path + sha256), and a non-empty settler
identity. The producer's narrative (`notes/`, `runs/worker-status-*`,
`runs/verification-*`, `runs/*-verify-note.md`, fact conclusions under
`facts/`, `evidence/verdict.json`) and the policy learning faces
(`runs/method-family-log.jsonl`, `runs/q-cell-log.jsonl`) SHALL be
refused BEFORE any read occurs, and a legal build SHALL open exactly
the artifact paths handed to it (never scan the workspace). The same
exclusion list SHALL be re-enforced at the settlement gate against
hand-built input docs.

#### Scenario: the learning faces are never settler input

- **WHEN** `settler_input` is asked to take
  `runs/method-family-log.jsonl` or `runs/q-cell-log.jsonl` as an
  artifact
- **THEN** it raises ValueError naming the exclusion, and a legal build
  over other artifacts opens neither file (poison sentinels in them
  never appear in the serialized input doc)

#### Scenario: the producer's narrative never enters the input doc

- **WHEN** `settler_input` is asked to take a notes/ or worker-status /
  verify-note / verification record, a fact file, or
  `evidence/verdict.json` as an artifact
- **THEN** it raises ValueError naming the exclusion, and a legal build
  neither opens any excluded face nor carries any of their sentinel
  bytes in the output doc

#### Scenario: a hand-built doc cannot smuggle an excluded face

- **WHEN** `settle_blind` receives an input doc whose artifacts list
  contains an excluded face (or a wrong schema stamp, or an empty
  identity)
- **THEN** nothing settles: the return carries `settled: false` and an
  `input:`-prefixed reason, and no ledger row is written

#### Scenario: aliased paths route nothing (case, dot segments, escapes)

- **WHEN** an artifact path is a case alias of a denied face
  (`Runs/Method-Family-Log.Jsonl`, `Notes/n.md` — the dev filesystem is
  case-insensitive), a dot/`..` alias (`runs/../notes/x.md`,
  `notes/./n.md`), or absolute/upward-escaping (`/etc/hosts`,
  `evidence/../../notes/x.md`)
- **THEN** the builder raises ValueError and the settlement gate
  refuses the hand-built doc — the exclusion compares resolved,
  normalized, case-folded paths, never raw strings; a rules-table path
  naming an excluded face segment is refused the same way

### Requirement: Settlement requires a named settler identity

Every input doc SHALL carry a non-empty settler identity (the
verifier-identity discipline). An empty or blank identity SHALL raise
at the builder and SHALL be refused at the settlement gate — credit
without a named grader does not settle.

#### Scenario: empty identity refuses at both doors

- **WHEN** `settler_input` is called with an empty identity, or
  `settle_blind` is called with a hand-built doc whose identity is blank
- **THEN** the builder raises ValueError and the settlement returns
  `settled: false` with an `input:` reason — no row lands

### Requirement: Re-running settlement on the same artifacts is byte-identical

Re-application of the same verdict doc over the same input doc SHALL
NOT churn the rollout ledger: the settlement engine's duplicate dedupe
(compared without `settled_ts`) refuses the second write even when the
caller passes a different clock, and the input build itself SHALL be
deterministic (same arguments → same bytes).

#### Scenario: duplicate settlement leaves the ledger bytes unchanged

- **WHEN** `settle_blind` runs twice on the same workspace with the
  same verdict doc, the same input doc, and DIFFERENT `now` timestamps
- **THEN** the first run settles (`settled: true`), the second reports
  the duplicate refusal, and `runs/rollout-ledger.jsonl` is
  byte-identical to its post-first-run bytes

#### Scenario: the input build is deterministic

- **WHEN** `settler_input` runs twice with the same arguments
- **THEN** the two docs serialize to identical bytes

### Requirement: The settler's own cost enters cost_t

`settle_blind` SHALL book the settler act's run cost (tokens, seconds)
through the transition ledger when the caller supplies a claim and
cost — the row's `r_incr` carries the `− LAMBDA · cost_t` term with
`cost_t = tokens/10000 + seconds/3600`, exactly like a producer act's
cost. The booking SHALL be launch-stash gated (no stash → no row, one
warn) so a repeated call cannot double-bill, and cost supplied WITHOUT
a claim SHALL be refused loudly before anything settles.

#### Scenario: the settler's tokens and seconds reduce r_incr

- **WHEN** `settle_blind` runs with `claim`, `cost_tokens=20000`, and
  `cost_seconds=3600` after an `action_type=settle` launch stash was
  recorded
- **THEN** a transition row lands with `action_type: settle` whose
  `r_incr` equals `ALPHA·ΔΦ − (20000/10000 + 3600/3600)` — i.e. the
  zero-cost `r_incr` minus exactly 3.0

#### Scenario: cost without a claim is a loud refusal

- **WHEN** `settle_blind` receives `cost_tokens` but no claim
- **THEN** the return carries `settled: false` and an `input:` reason —
  spend is never dropped silently and no ledger row is written

#### Scenario: a re-run cannot double-bill the settler

- **WHEN** `settle_blind` runs a second time with the same claim and
  cost arguments after the first call booked the settle transition
- **THEN** the second call reports the duplicate settlement and books
  no cost row (`settler_cost` is None — the launch stash was consumed
  by the first close) and `runs/transitions.jsonl` stays byte-identical
