# plan-drift-repair-verification delta — issue-281-plan-repair-verify

## ADDED Requirements

### Requirement: plan-drift REJECT opens a repair episode (issue-281)

The detector SHALL open a repair episode in `runs/plan-repair-state.json`
when check() runs a detection round whose drift set is non-empty
(REJECT-class rounds; STALE_PLAN_ON_NEW_EVIDENCE warns are never drift and
can never open an episode) and no repair episode is open. The episode
SHALL carry the fingerprint (sorted `TYPE:claim_id` items plus the class
list, telemetry for the CURRENT shape) and `rounds = 1` (the opening
round itself counts toward the cumulative window). The opening round
SHALL NOT change the detector's stdout, stderr, or exit code.

#### Scenario: first drift round opens silently

- **WHEN** the detector reports its first REJECT-class drift on a
  workspace with no open episode
- **THEN** the state file records the fingerprint with rounds=1 and the
  check's printed report and exit code are unchanged

#### Scenario: a clean workspace writes no state

- **WHEN** every detection round is drift-free and no episode is open
- **THEN** no state file is ever created

### Requirement: bounded-window verification with re-escalation cadence (issue-281)

The detector SHALL advance a cumulative, fingerprint-INDEPENDENT drift-
round counter on EVERY detection round whose drift set is non-empty (a
rotating drift shape can never reset the window), and SHALL emit a
`plan_repair_overdue` event row (detail JSON carrying the current
fingerprint items, rounds, and window) plus an stderr escalation line
each time the counter reaches a multiple of `PLAN_REPAIR_WINDOW_ROUNDS`
(named constant, value 3). Escalation SHALL be visibility-only — never a
new block and never an exit-code change (the drift REJECT itself still
gates dispatch).

#### Scenario: un-repaired drift escalates at the window

- **WHEN** drift persists for PLAN_REPAIR_WINDOW_ROUNDS consecutive
  detection rounds
- **THEN** the third round emits one plan_repair_overdue row (detail
  rounds=3) and a stderr line, while the exit code stays 1 (or 2 for 3+
  items) exactly as before

#### Scenario: rotating drift shapes cannot reset the window

- **WHEN** the drift set alternates between two disjoint shapes (e.g.
  ORPHAN_CLAIM:C-2 / STALE_PLAN_ENTRY:C-9) across the window
- **THEN** the counter keeps accumulating across shape changes, overdue
  fires on schedule (rounds 3, 6, 9), and no plan_repair_verified row is
  ever emitted

#### Scenario: cadence, not once-forever

- **WHEN** drift continues past the first escalation (rounds 4, 5, 6, ...)
- **THEN** overdue re-fires at each subsequent multiple of the window
  (rounds 6, 9, ...) — one row per window of continued drift, never
  permanent silence and never re-emit spam within a window

### Requirement: repair-landed path closes the loop visibly (issue-281)

The detector SHALL close an open episode as verified — emitting a
`plan_repair_verified` event row and printing a verified line — ONLY on a
genuinely clean detection round (drift-free), and SHALL NOT emit
plan_repair_verified for any other transition (drift changing shape is
not evidence of repair). A changed fingerprint SHALL supersede the
recorded shape in place (same episode continues, no event, the cumulative
window does not reset). After a verified close, a new drift episode SHALL
start with the counter reset.

#### Scenario: amendment lands, next round clean

- **WHEN** the plan files are amended so the next detection round is
  drift-free
- **THEN** one plan_repair_verified row lands (detail rounds = the
  cumulative drift rounds it took), the state closes as verified, and a
  later new drift starts a fresh episode at rounds=1

#### Scenario: late repair after escalation still closes the loop

- **WHEN** the amendment lands only after the overdue escalation
- **THEN** the episode still closes verified (the loop closes visibly)

#### Scenario: fingerprint rotation is not repair

- **WHEN** the drift set changes to a disjoint shape on a later round
- **THEN** the episode continues with the new fingerprint, the counter
  keeps accumulating, and no plan_repair_verified row is emitted

### Requirement: fail-open posture (issue-281)

The verification SHALL never alter the detector's verdict or crash any
face. An unreadable state file SHALL skip verification for the round with
a stderr annotation; any unexpected tick error SHALL be caught and
reported on stderr; state and event writes SHALL be best-effort. The
verification SHALL read the same plan files the detector reads (one
source) and SHALL run on every face that runs the detector (operator CLI,
--auto dispatch-gate face, hooks gate subprocess) without any
hooks-side re-implementation.

#### Scenario: unreadable state skips verification

- **WHEN** runs/plan-repair-state.json exists but cannot be parsed
- **THEN** the check returns the same verdict, annotates the skip on
  stderr, and emits no repair events

#### Scenario: adversarial state writes are accepted, bounded

- **WHEN** a worker forges or resets runs/plan-repair-state.json (runs/
  is a worker surface; write_guard's contract covers the four carriers
  only)
- **THEN** the acceptance is explicit: the face is additive
  observability — the dispatch verdict never depends on the state (the
  drift REJECT is re-derived from the workspace every round), a planted
  state cannot manufacture drift-free rounds (verified requires the
  detector's own clean round), and the state follows the accepted
  runs/.retry-counter.yaml forgery-class precedent

#### Scenario: both event words are registered

- **WHEN** the event taxonomy lists emitter actions
- **THEN** plan_repair_overdue and plan_repair_verified are present and
  the list stays sorted and unique

### Requirement: cross-face window sync (issue-281)

The sinks drift REJECT guidance SHALL name the bounded-window
verification — and so SHALL the workspace template's global_plan.txt
carrier row — with the same window number as the detector constant,
pinned by tests (literal-duplication posture, single source in
scripts/plan_drift_detector.py).

#### Scenario: guidance names the verification

- **WHEN** the drift REJECT guidance text is read
- **THEN** it names plan_repair_overdue and states the same
  "3 detection rounds" window the detector enforces
