## ADDED Requirements

### Requirement: DEAD SHALL be a member of status_defs.TERMINAL
The `status_defs.TERMINAL` set is the single source of truth for "claim is closed, needs no more work". It MUST include `"DEAD"` so any consumer testing `status not in TERMINAL` treats a poison / exhausted claim (promotion_attempts >= 3, explicitly killed) as closed and excludes it from dispatch. DEAD MUST NOT appear in `PARTIAL_STATUSES` or `IN_PROGRESS_STATUSES` — a DEAD claim needs no further work and is not in-flight. This follows the #34 operating manual and mirrors the #59 SUPERSEDED landing.

#### Scenario: DEAD recognized as terminal
- **WHEN** `status_defs.TERMINAL` is inspected
- **THEN** `"DEAD"` MUST be a member of the set and the set MUST have exactly 8 values: PROVEN, VERIFIED, NEGATIVE, REFUTED, DEFERRED, STALE, SUPERSEDED, DEAD

#### Scenario: DEAD is not partial nor in-progress
- **WHEN** `PARTIAL_STATUSES` and `IN_PROGRESS_STATUSES` are inspected
- **THEN** `"DEAD"` MUST NOT be a member of either set

### Requirement: dead_letter.mark_dead SHALL write DEAD plus a quarantine artifact
`scripts/dead_letter.py::mark_dead(workspace, claim_id, reason)` SHALL set the claim's `status` to `DEAD` and add a `dead_at` ISO timestamp and a `dead_reason` string to the claim in `claim-register.yaml` (mirroring the STALE write pattern). It SHALL also create `blockers/dead-letter-<claim_id>.md` recording the exit reason, the `dead_at` timestamp, the `promotion_attempts` count, and a pointer to the failure history. The `blockers/` directory SHALL be created if absent. When the claim id is not found, `mark_dead` SHALL return a `{"marked": False, "reason": ...}` dict and write nothing.

#### Scenario: exhausted claim is marked DEAD with an artifact
- **WHEN** `mark_dead(workspace, "C-2", reason="3 attempts exhausted")` runs against a register containing claim `C-2` with `promotion_attempts: 3`
- **THEN** the claim's status becomes `DEAD`, the register records `dead_at` and `dead_reason`, and `blockers/dead-letter-C-2.md` exists

#### Scenario: unknown claim is rejected
- **WHEN** `mark_dead(workspace, "C-404")` runs against a register with no such claim
- **THEN** the return dict has `marked` = False, no file is written, and the register is unchanged

### Requirement: dead_letter.scan SHALL report exhausted-but-not-terminal claims
`scripts/dead_letter.py::scan(workspace)` SHALL return the ids of claims whose `promotion_attempts >= 3` and whose status is NOT in `status_defs.TERMINAL`. Claims already DEAD (or any other terminal status) SHALL be excluded. The scan is read-only: it SHALL NOT modify the register.

#### Scenario: dangling exhausted claim is reported
- **WHEN** a register has a claim with `status: OPEN` and `promotion_attempts: 3`
- **THEN** `scan` returns a list containing that claim's id

#### Scenario: already-DEAD claim is not reported
- **WHEN** a register has a claim with `status: DEAD` and `promotion_attempts: 3`
- **THEN** `scan` returns an empty list (DEAD is terminal)

### Requirement: dead_letter.detect_dirty_statuses SHALL flag non-enum status literals
`scripts/dead_letter.py::detect_dirty_statuses(workspace)` SHALL return the ids of claims whose `status` literal is not in the legal status set (the union of `TERMINAL`, `ACTIVE_STATUSES`, `PARTIAL_STATUSES`, `IN_PROGRESS_STATUSES`, and the legacy pseudo-statuses STAMP and UNVERIFIED). Non-enum values like `PASS-` SHALL be flagged. The check is read-only: it SHALL NOT modify the register.

#### Scenario: PASS- dirty value is detected
- **WHEN** a register has claim `C-4` with `status: PASS-`
- **THEN** `detect_dirty_statuses` returns a list containing `C-4`

#### Scenario: clean register yields no dirty statuses
- **WHEN** every claim's status is in the legal set
- **THEN** `detect_dirty_statuses` returns an empty list

### Requirement: worker_pulse SHALL surface a quarantined count flag
`hooks/worker_pulse.py::_build_pulse` SHALL append `quarantined=N` to the flags line when the workspace has one or more DEAD claims, where N is the count of DEAD claims in `claim-register.yaml`. The flag SHALL be omitted when N is 0 (matching the existing omit-zero style of the partial/blockers flags).

#### Scenario: workspace with a DEAD claim shows quarantined=1
- **WHEN** a worker completes and the workspace has exactly one claim whose status is `DEAD`
- **THEN** the pulse flags line contains `quarantined=1`

#### Scenario: workspace with no DEAD claim omits the flag
- **WHEN** a worker completes and the workspace has zero DEAD claims
- **THEN** the pulse flags line does NOT contain a `quarantined=` entry
