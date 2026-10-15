# settler-read-barrier-687 delta — issue-687-blind-settlement

## ADDED Requirements

### Requirement: The read barrier identifies settler acts mechanically

The read barrier SHALL treat the settler agent family
(`kunglao-settler` / `settler` markers) as a blind identity class with
the same posture as the red-team class: identity resolved from the
subagent `agent_type` when present (authoritative), else from the
UserPromptSubmit-armed session's recorded dispatch agent — a dispatch
envelope whose `agent` names the settler arms its top-level session,
and arming SHALL remain recorder-only (never blocks a prompt).
Non-blind callers (workers, the unarmed orchestrator) SHALL be
untouched.

#### Scenario: a settler subagent read of a denied face is rejected

- **WHEN** a tool call carries `agent_type: kunglao-settler` and its
  target is `notes/`, `runs/worker-status-*`, `runs/verification-*`,
  `runs/*-verify-note.md`, `facts/`, `evidence/verdict.json`,
  `runs/method-family-log.jsonl`, or `runs/q-cell-log.jsonl`
- **THEN** the barrier returns rc=2 with `REJECT rt_read_barrier` on
  stderr and repair context naming the allowed working faces

#### Scenario: a settler's raw-artifact working face stays open

- **WHEN** a `kunglao-settler` tool call reads a raw artifact under
  `evidence/` (excluding `evidence/verdict.json`)
- **THEN** the barrier returns rc=0 with no message

#### Scenario: the armed settler session rides the same deny list

- **WHEN** a UserPromptSubmit prompt carries the v1 dispatch envelope
  with `agent: kunglao-settler`, and that session later reads a denied
  face without an `agent_type`
- **THEN** the read is rejected rc=2; a worker envelope in the same
  session shape is never armed and its reads pass rc=0

### Requirement: Both blind families are denied the policy learning faces

The deny list SHALL include `runs/method-family-log.jsonl` and
`runs/q-cell-log.jsonl` for EVERY blind identity (red-team and settler)
across all barrier tool faces: targeted Read, Glob/Grep patterns naming
the files, and Bash commands carrying the path tokens.

#### Scenario: an RT act is denied the learning logs

- **WHEN** a `kunglao-redteam` tool call reads
  `runs/method-family-log.jsonl` or `runs/q-cell-log.jsonl`
- **THEN** the barrier returns rc=2 (the logs joined the shared deny
  face)

#### Scenario: Bash and pattern faces carry the same denial

- **WHEN** a settler act runs a Bash command containing a learning-log
  path token, or a Glob/Grep pattern naming one
- **THEN** the barrier returns rc=2

### Requirement: Blindness survives path aliases and blank arm rows

All barrier path/token comparisons SHALL be case-folded (the dev
filesystem is case-insensitive: `Notes/n.md` must deny like
`notes/n.md`, on Read, Bash, and Glob/Grep faces), and an armed session
whose recorded dispatch agent is blank or unrecognized SHALL remain
blind (arming only ever restricts; the family merely selects the reject
message).

#### Scenario: case-variant aliases are denied

- **WHEN** a blind act reads `Runs/Method-Family-Log.Jsonl`,
  `Notes/n.md`, `Facts/F001.md`, or `Runs/Worker-Status-W1.MD`, or runs
  `cat Notes/n.md`
- **THEN** every call is rejected rc=2

#### Scenario: a blank-agent arm row stays blind

- **WHEN** a session carries a live arm whose recorded agent is empty
  and its tool call reads a denied face
- **THEN** the read is rejected rc=2

### Requirement: A blind act's own liveness file is its one status exemption

A blind act MUST be able to read and append its OWN status file
(`runs/worker-status-<own-agent>-<id>.md`) — narrative-free by
construction (the act itself is the only writer). Every foreign
`worker-status-*` file (any family, any case) stays denied, and a Bash
command mixing the act's own status path with any foreign worker-status
token denies as a whole.

#### Scenario: own status allowed, foreign status denied

- **WHEN** a settler act Reads or Bash-appends
  `runs/worker-status-kunglao-settler-<id>.md`
- **THEN** the call passes rc=0; the same act Reading the redteam's or
  any worker's status file, or a Bash command naming both its own and a
  foreign status file, is rejected rc=2
