# issue-458-online-distillation — spec delta: online-distillation

## ADDED Requirements

### Requirement: Shelf-miss becomes a first-class mechanical trigger

The system SHALL detect exactly two runtime miss signals and no
others: (a) a structured `shelf-miss: <capability-token>` marker line
in a worker status file (`runs/worker-status-*.md`) — the LLM worker's
full-shelf semantic-selection verdict, where the capability token is
free-form worker vocabulary and is NEVER resolved through a rules
table, alias map, or applies_to registry; and (b) an unknown-format
probe failure read from the REAL producers' evidence shapes —
`evidence/die.json` that is present and usable (at least one DIE call
produced a data block) with a falsy `derived.language`, or
`evidence/apkid.json` with `status == "ok"` and empty `findings` —
never by re-running a probe. A probe operational error (`status:
"error"`), a missing evidence file, or a workspace without either
signal SHALL produce no trigger. Detection SHALL be a mechanical scan
in a single engine module consumed by both hosts (the e2e dispatch
loop's post-wave tick step and the production SubagentStop closure
hook), the production face SHALL be fail-open (a scan failure is one
rate-limited warn; the subagent's stop path is never disturbed), and
the scan SHALL only read worker-status files whose mtime is at or
after the ledger's `run_started_ts` and never a file the ledger
already recorded as a consumed marker.

#### Scenario: marker triggers the signal

- **WHEN** a fresh worker status file (mtime at or after the run
  start, not yet consumed) carries `shelf-miss: crypto:decode
  sample=target/blob.bin` and the trigger scan runs
- **THEN** the scan returns one trigger of kind `shelf-miss` with the
  token and the sample hint

#### Scenario: no marker, no trigger

- **WHEN** the workspace holds ordinary worker status files and probe
  evidence with concrete classifications
- **THEN** the scan returns no trigger and no distillation act is
  dispatched (negative pin: claim failures, timeouts, tool exit
  codes, and probe operational errors never imply a miss)

#### Scenario: unknown-format probe failure triggers

- **WHEN** `evidence/die.json` holds at least one usable data block
  and its `derived.language` is null/falsy
- **THEN** the scan returns one trigger of kind `format-unknown`
  whose token is `format:unknown:evidence/die.json`

#### Scenario: probe operational error is no-signal

- **WHEN** `evidence/apkid.json` carries `status: "error"`
- **THEN** the scan returns no trigger (an infra failure is not a
  miss)

#### Scenario: stale marker does not re-fire

- **WHEN** a marker file predates the ledger's `run_started_ts` or is
  recorded in `consumed_markers`
- **THEN** the scan skips it and no trigger fires for it

#### Scenario: production closure face is fail-open

- **WHEN** the SubagentStop closure runs the trigger scan and the
  scan raises
- **THEN** the closure row still lands, rc stays 0, and the failure
  is one rate-limited warn

### Requirement: Distillation dispatch is budget-first and fail-closed

A distillation act SHALL dispatch only when the budget ledger
(`<ws>/runs/distill-budget.json`, schema `distill-budget/1`, the
mission_ledger counter pattern: atomic whole-document writes under a
workspace-scoped lock) allows it: a per-run hard act cap (default 2),
a per-run hard hop budget (default 12), and a per-run trigger memory
keyed by trigger token — the marker's capability token for
shelf-miss, the fixed token `format:unknown:<evidence-file>` for
format-unknown — where a second trigger on an already-triggered
token records a skipped duplicate, never a second act. Run identity
SHALL be engine-minted and monotone: per-run counters reset ONLY at
the explicit engine re-init face (a freshly minted id); no caller-,
session-, or workspace-supplied run id resets anything, and the
production closure host never resets the counters. Caps SHALL never
loosen: a stored budget above the module default clamps down to the
default at load, no configuration face may raise a cap, and a stored
budget below the default is honored. An unreadable or corrupt ledger
SHALL read as exhausted (fail-closed) with the refusal recorded as a
`distill_result` row carrying `phase="refused"` and the reason. The
ledger SHALL carry a workspace-lifetime `global` counter (acts,
hops, landed) that never resets and caps nothing — the frequency
observation face for the restraint ruling.

#### Scenario: budget allows, act dispatches

- **WHEN** a trigger fires with act budget and hop budget remaining
  and the token not yet triggered this run
- **THEN** one distill act dispatches, the ledger debits one act
  unit, and a `distill_attempt` row with `phase="dispatched"` lands
  in the unified audit stream

#### Scenario: per-run cap halts

- **WHEN** the run already consumed its per-run act budget and a new
  trigger fires
- **THEN** no act dispatches and a `distill_result` row with
  `phase="refused"` records the remaining-zero budget state

#### Scenario: duplicate token does not re-trigger

- **WHEN** a marker on token `crypto:decode` fires after that token
  already triggered this run
- **THEN** the trigger is recorded as a skipped duplicate and no
  second act dispatches

#### Scenario: corrupt ledger fails closed

- **WHEN** the budget ledger is unreadable or not valid JSON
- **THEN** the budget reads as exhausted, no act dispatches, and the
  refusal row carries `budget_ledger_unreadable`

#### Scenario: caps never loosen

- **WHEN** a ledger stores `per_run_budget` greater than the module
  default
- **THEN** the effective budget is the module default (clamped at
  load), while a stored smaller budget is honored

#### Scenario: caller-supplied run identity resets nothing

- **WHEN** a caller or workspace file presents a run id different
  from the ledger's
- **THEN** the per-run counters do not reset (only the engine
  re-init face mints a new run)

### Requirement: Mixed-source retrieval is methodology-first with hard expansion caps

The distillation act SHALL retrieve from the local re-library first
(references/re-library/ incl. case-distilled, osint, and formats
lanes) and then the web search face; every consulted source SHALL be
recorded in the attempt's report — local refs SHALL resolve to real
repo files (a fabricated local citation rejects the report) and web
refs SHALL carry URL and access date and SHALL be marked advisory
(never directly PROVEN). Imperfectly-matched sources SHALL be mined
for METHODS (decision rules, branch tables, mental models) with case
specifics discarded; the report SHALL carry at least one method (a
report with zero methods rejects). Recursive case expansion SHALL be
hard-capped: depth cap 1 (a branch source may never serve as another
hop's root — no chains), breadth cap 3 (at most 3 branch hops per
root source), every hop consumes one hop-unit of the per-run hop
budget, and a report whose hops violate the caps or exceed the
remaining hop budget rejects whole — its candidates never reach the
oracle.

#### Scenario: local-first with resolvable sources

- **WHEN** the report cites one re-library card that exists and one
  web URL with an access date
- **THEN** the report passes source validation and the sources are
  recorded in the audit row detail

#### Scenario: fabricated local citation rejects

- **WHEN** the report cites a re-library path that does not exist in
  the repo
- **THEN** the report rejects with the citation named in the
  violations and no candidate runs

#### Scenario: depth cap is hard

- **WHEN** the report carries a hop whose root is itself another
  hop's branch (a chain of depth 2)
- **THEN** the report rejects whole with a depth-cap violation

#### Scenario: breadth cap is hard

- **WHEN** the report carries more than 3 branch hops under one root
  source
- **THEN** the report rejects whole with a breadth-cap violation

#### Scenario: remaining hop budget is the binding total

- **WHEN** a caps-legal report's hop count exceeds the ledger's
  remaining per-run hop budget
- **THEN** the report rejects whole and the ledger's `hops_used`
  debits nothing

#### Scenario: hops debit the ledger

- **WHEN** a validated report carries N hops
- **THEN** the ledger's `hops_used` increases by exactly N and the
  global hops counter accumulates

### Requirement: Candidates run against the anchored sample bytes

The engine — never the act — SHALL resolve the oracle sample from
the workspace's anchored sample face (the declared analysis material
the run is about) and execute every distilled candidate as a bounded
subprocess against those bytes; the marker's `sample=` hint SHALL be
validated against the anchor (mismatch = recorded no-oracle, no
landing), an anchorless workspace falls back to the guarded marker
path with the fallback marked in the audit row, and a candidate
manifest's sample path is never trusted (the engine injects the
resolved one). The outcome (rc, stdout digest, tail, declared-
expectation conformance, the resolved sample's sha256) SHALL be
recorded in the `distill_result` audit row. A candidate that cannot
run (no resolvable sample, subprocess failure, timeout) SHALL record
its outcome honestly and SHALL NOT land. The oracle judges mechanical
conformance only (declared rc, stdout marker, non-empty output);
every tier-1 landing SHALL carry `oracle_self_declared: true` —
semantic quality stays with the post-run promotion gate.

#### Scenario: candidate runs the anchored bytes and lands

- **WHEN** a validated candidate's oracle run against the resolved
  anchored sample exits with the declared rc and its stdout carries
  the declared marker
- **THEN** the outcome is recorded as satisfied (with the sample
  sha256), the flag `oracle_self_declared` is carried, and the
  candidate lands run-local

#### Scenario: marker hint mismatch records no-oracle

- **WHEN** the marker's `sample=` hint disagrees with the anchored
  sample
- **THEN** the attempt records a no-oracle outcome and nothing lands

#### Scenario: failed oracle run never lands

- **WHEN** the candidate exits nonzero, prints no marker, or times
  out
- **THEN** the unsatisfied outcome is recorded and nothing lands in
  tools-local

### Requirement: Landing is tiered and the global shelf has no runtime write face

A candidate whose oracle was satisfied SHALL land in tier 1 only:
`<ws>/tools-local/<name>.py` plus `<name>.manifest.json` carrying
provenance (name, capability, attempt id, sources, hops, methods,
oracle outcome with the anchored sample sha256 and the
`oracle_self_declared` flag, landed timestamp) — immediately usable
in-run. Landing SHALL emit one `candidate_landed` audit row per
landed candidate. The engine SHALL expose NO write face to the global
shelf (tools/, references/re-library/); promotion to the global shelf
remains a post-run wave task through the EXISTING distill quality
gate (generality + heuristic value) reading the landed manifests.
The worker-facing dispatch documentation SHALL name `tools-local/`
as a read face for in-run distilled tools.

#### Scenario: run-local landing with provenance

- **WHEN** a candidate lands
- **THEN** `tools-local/<name>.py` and its manifest exist, the
  manifest carries the attempt's sources/hops/methods and the oracle
  outcome with the sample sha256, and one `candidate_landed` row
  lands in the stream

#### Scenario: worker documentation names the run-local shelf

- **WHEN** the worker-facing dispatch documentation is inspected
- **THEN** it names `tools-local/` as a place workers read in-run
  distilled tools (pinned by a documentation test)

#### Scenario: global shelf unreachable at runtime

- **WHEN** any code path in the engine attempts a write under the
  repo's tools/ or references/ trees
- **THEN** no such face exists (statically pinned by test: the
  engine module declares no write target outside the workspace's
  runs/, tools-local/, and distill-candidates/ trees)

### Requirement: The distillation vocabulary SHALL ride the unified audit stream

The distillation vocabulary SHALL register three action words —
`distill_attempt`, `distill_result`, `candidate_landed` — in the
unified 17-field stream's controlled vocabularies where the
established changes encoded them: the e2e stream vocabulary (`scripts/e2e/audit.py`
AUDIT_ACTIONS, with a `distill` report category) and the production
emit vocabulary (`scripts/event_taxonomy.py` EMIT_ACTIONS); every
row SHALL carry the 17-field schema with structured detail JSON, the
capability token in `detail.capability` (the attribution `arm` stays
null for distill rows). Exactly-one guarantees, per distill
vocabulary word, alongside the standard dispatch pair the faces
already emit for any act: one `distill_attempt` row per dispatched
act (`phase="dispatched"`), where the production closure's signal
row (`phase="triggered"`) is an explicitly documented exemption (the
production act is the orchestrator's decision and may never follow);
one `distill_result` row per dispatched attempt (rejections
included) plus one `phase="refused"` row per budget refusal keyed to
the trigger; one `candidate_landed` row per landed candidate.

#### Scenario: vocabulary registered on both streams

- **WHEN** the vocabularies are inspected
- **THEN** all three words are present in AUDIT_ACTIONS and
  EMIT_ACTIONS, and the e2e report buckets them under `distill`

#### Scenario: exactly one row of each kind per dispatched act

- **WHEN** a distill act dispatches, its report validates, and its
  candidate lands
- **THEN** the stream holds exactly one distill_attempt(dispatched)
  row, one distill_result row, and one candidate_landed row for the
  attempt — no twins of any distill word

### Requirement: A constructed fixture SHALL prove the full chain on a genuine miss

A committed, constructed fixture SHALL drive the full chain in a
dry-mode e2e: generator + synthetic sample + a re-library methodology
card whose method solves it (zero real-sample bytes); the shelf
genuinely misses (the transform is absent from the registered crypto
tools), the marker fires the trigger, the budgeted act produces a
report citing the card, the engine validates it, the candidate runs
against the anchored sample bytes and satisfies its oracle, and the
candidate lands in tools-local with the audit trail complete. The
miss is genuine when no registered crypto subcommand, over its
documented parameter space as pinned by the test, reproduces the
fixture's expected plaintext digest or magic header.

#### Scenario: full chain green

- **WHEN** the fixture e2e runs against a workspace staged with the
  fixture sample and a shelf-miss marker
- **THEN** trigger → budgeted act → validated report → satisfied
  oracle → run-local landing all occur, the stream holds the three
  row kinds, and the budget ledger reflects the spent act and hops

#### Scenario: the miss is genuine

- **WHEN** the fixture sample is offered to every registered crypto
  transformation subcommand over the parameter space the pin test
  sweeps
- **THEN** none reproduces the fixture's expected plaintext digest
  or magic header (the fixture transform is outside the shelf — the
  trigger premise is honest)
