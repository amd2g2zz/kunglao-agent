# gate-chain-power spec

## ADDED Requirements

### Requirement: init SHALL leave a non-empty task-oracle.yaml in every initialized workspace

`kunglao-init.py` initialize() SHALL write `task-oracle.yaml` at the
workspace root after deploy_env. Init has no user task text, so the file
SHALL be a structured skeleton (`task_text: pending-user-input-backfill`,
empty `open_items`/`deferrals`, `registered_ts`) — non-empty on disk. The
write SHALL be idempotent (a pre-existing oracle is never clobbered) and
SHALL NOT change the claim-register state hash inputs (the oracle is a
workspace artifact, not scaffold state). The orchestrator's Phase 1 SHALL
backfill the user's verbatim task into `task_text` before the first
dispatch.

#### Scenario: fresh init produces the oracle skeleton

- **GIVEN** a workspace initialized by kunglao-init (exit 0)
- **WHEN** the workspace is inspected
- **THEN** `task-oracle.yaml` exists, parses as YAML, and is non-empty with
  a `registered_ts`

#### Scenario: re-init never clobbers a backfilled oracle

- **GIVEN** a workspace whose task-oracle.yaml carries the user's task text
- **WHEN** init re-runs (resume mode)
- **THEN** task-oracle.yaml is byte-identical (resume exits before scaffold)

### Requirement: the heartbeat tick SHALL report oracle registration

`heartbeat_tick.py` SHALL include an `oracle_registered` boolean in the
tick report (true iff `<workspace>/task-oracle.yaml` exists and is
non-empty). A false value SHALL print one actionable line to stdout naming
the missing registration. The check SHALL be fail-open (an unreadable
oracle reads as registered=false, never crashes the tick) and SHALL NOT
by itself change the tick exit code (the selfcheck/renew/heartbeat rc
weights stay authoritative).

#### Scenario: missing oracle surfaces in the tick

- **GIVEN** a workspace with no task-oracle.yaml
- **WHEN** heartbeat_tick.py runs
- **THEN** the report carries `oracle_registered: false` and stdout names
  task-oracle.yaml registration

### Requirement: the declaration detector SHALL fire on the handoff-escape register

`premature_termination_detect.py` SHALL extend its pattern families so the
2026-08-18 four-step closing escape fires at least 3 of its fingerprints,
while a clean completion (zero-open assertion, no imperatives, no
handoff/tier/cost phrases) still fires zero:

- F2 (self-invented tiering) SHALL include human-handoff keywords
  (手动 / 人工 / manual / GUI / dump 给我) — assigning the user manual work
  the task never authorized is tier invention.
- F3 (cost-semantic drift) SHALL include time-cost figures (N 小时 / N
  分钟 / N min / N hours) under the same sentence-co-occurrence qualifier
  as currency figures.
- F4 (false completion) SHALL include semantic-equivalent completion
  phrases (我能做的都做了 / 我能继续的事都已经做了 / nothing more I can
  do).

#### Scenario: the four-step escape narration fires >= 3 fingerprints

- **GIVEN** the sanitized 2026-08-18 narration (self-completion /
  1-2h-manual tier / session-cost stop / user imperative handoff)
- **WHEN** detect() runs
- **THEN** `fired_count >= 3`

#### Scenario: clean completion stays at zero

- **GIVEN** a declaration with zero-open assertion, no imperative, no
  handoff/tier/time-cost phrase
- **WHEN** detect() runs
- **THEN** `fired_count == 0`

### Requirement: user-directed imperatives with open items SHALL block (F5)

detect() SHALL implement an F5 "user-delegation escape" fingerprint: a
user-directed imperative pattern (你打开 / 你装上 / 你接着干 / 你来 / 手动跟 /
dump 给我) co-occurring with open-items-remaining signals in the same
declaration → F5 fires. No imperative, or an imperative with a zero-open
assertion → F5 stays quiet (precision guard).

#### Scenario: imperative handoff with open items blocks

- **GIVEN** a closing declaration containing "你能继续的路: ... 把字节码
  dump 给我" and open-item signals
- **WHEN** detect() runs
- **THEN** F5 fires with the imperative evidence span

### Requirement: needs-human declarations SHALL demand tool-search zero-hit evidence

When detect() finds a needs-human/cannot-automate assertion (需人工 /
无法自动化 / 手动), the report SHALL carry
`require_evidence: ["tool_search_zero_hit"]` — the declaration is legal
only with tools/_INDEX.yaml + tool-search zero-hit proof attached. The
detector performs the mechanical existence check only; the runtime
completion is toolfirst-side.

#### Scenario: needs-human assertion carries the evidence duty

- **GIVEN** a declaration asserting "需要 1-2 小时纯人工 RE"
- **WHEN** detect() runs
- **THEN** the report carries `require_evidence` containing
  `tool_search_zero_hit`
