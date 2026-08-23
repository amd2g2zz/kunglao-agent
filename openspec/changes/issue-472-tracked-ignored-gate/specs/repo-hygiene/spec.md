# tracked-vs-ignored gate spec

## ADDED Requirements

### Requirement: the repository SHALL contain zero tracked-but-ignored files outside an explicit allowlist

The test suite SHALL enforce a global invariant: every path reported by
`git ls-files` is cross-checked against the ignore rules via
`git check-ignore --no-index` (the `--no-index` flag is mandatory — default
check-ignore is index-aware and silently answers "not ignored" for tracked
files, which is the exact structural hole that leaked #454/#455/#472). Any
tracked-but-ignored path not present in the `TRACKED_IGNORED_ALLOWLIST`
constant (with per-entry justification) SHALL fail CI with the named file
list. Every allowlist entry SHALL additionally be re-verified on each run:
an entry that is no longer tracked-but-ignored (stale) SHALL fail the
allowlist hygiene assertion so the allowlist cannot rot into a blind spot.
`.gitignore` rules themselves SHALL NOT be modified by this enforcement.

#### Scenario: legacy process artifact is flagged

- **GIVEN** `.review/baseline-failures.txt` is tracked while `.gitignore` contains `.review/`
- **WHEN** `tests/test_no_tracked_ignored_files.py` runs
- **THEN** it FAILS and the assertion message names `.review/baseline-failures.txt`

#### Scenario: a fresh `git add -f` leak is flagged

- **GIVEN** an operator runs `git add -f .review/tmp.txt` on an ignored path
- **WHEN** the gate runs
- **THEN** it FAILS listing `.review/tmp.txt` (witnessed on this branch; the staged leak was reset, not committed)

#### Scenario: legitimate golden fixtures pass via allowlist

- **GIVEN** the four `tests/fixtures/golden/F-0{3,6}/ws/runs/worker-status-*.md` fixtures are tracked and matched by the bare `runs/` rule at depth
- **WHEN** the gate runs
- **THEN** they are excluded by `TRACKED_IGNORED_ALLOWLIST` and the gate PASSES
