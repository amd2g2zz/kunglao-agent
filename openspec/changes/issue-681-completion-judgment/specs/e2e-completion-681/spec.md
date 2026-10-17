# e2e-completion-681 delta — issue-681-completion-judgment

## ADDED Requirements

### Requirement: Completion is the independent checker's verdict on the delivered candidate

When a run stops short of ALL-PASS on a delivery-starved label
(BLOCKED or PARTIAL) and a candidate exists at the unit's contract
path, the pipeline SHALL run the unit's own checker on that candidate
at finalize (the ORACLE judgment, even when the stage loop broke
before reaching it). An ORACLE PASS SHALL set the final label to the
distinct `checker-PASS` with exit 0; an ORACLE non-PASS SHALL keep the
pipeline's own label and exit code. A checkpoint FAIL SHALL stay FAIL
regardless of the checker's verdict. The finalize-time ruling SHALL be
fail-open: any checker trouble warns once and never loses the report.

#### Scenario: a blocked run with a checker-PASSING delivery is completion

- **WHEN** the stage loop breaks BLOCKED (e.g. C7 convergence never
  lands) and the unit's checker VERDICT PASSes the candidate at the
  contract path
- **THEN** the report's final_status is `checker-PASS` (never
  BLOCKED/PARTIAL), the exit code is 0, the ORACLE result lands in the
  checkpoint table with its evidence, and the blocked stage row stays
  BLOCKED (nothing laundered)

#### Scenario: a checker FAIL keeps the pipeline's own label

- **WHEN** the run is BLOCKED (or budget-PARTIAL) with a delivered
  candidate and the checker's verdict is FAIL
- **THEN** final_status and exit code are unchanged (BLOCKED stays
  BLOCKED, PARTIAL stays PARTIAL)

#### Scenario: a checkpoint FAIL is never upgraded

- **WHEN** a checkpoint hard-FAILs (e.g. a promotion-gate violation)
  with a candidate present in the workspace
- **THEN** final_status stays FAIL and the exit code stays
  EXIT_CHECKPOINT_FAIL — a checker PASS does not launder a defect

### Requirement: The best-so-far candidate is always delivered

Every finalize SHALL write `runs/deliverable-best-so-far.json` in the
workspace while a candidate exists at the unit's contract path,
carrying the schema stamp, run/unit/family ids, the final label, the
ws-relative candidate path, and the candidate's sha256. The file SHALL
never be deleted when a later finalize finds no candidate (monotone
hand-off). When no candidate exists, no file SHALL be written.

#### Scenario: a PARTIAL run hands its candidate over

- **WHEN** a budget-exhausted PARTIAL run leaves a candidate at the
  contract path
- **THEN** runs/deliverable-best-so-far.json exists and points at that
  candidate (ws-relative path + digest), whatever the checker verdict

#### Scenario: a run with no candidate delivers nothing

- **WHEN** finalize runs and no file exists at the unit's contract
  path
- **THEN** runs/deliverable-best-so-far.json is not created
