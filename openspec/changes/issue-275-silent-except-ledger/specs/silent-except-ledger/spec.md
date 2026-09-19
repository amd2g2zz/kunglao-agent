# issue-275-silent-except-ledger — spec delta: silent-except-ledger

## ADDED Requirements

### Requirement: Mechanical silent-swallow detector

The silent-except gate SHALL count, per file over `scripts/` and
`hooks/`, every `except` handler whose body consists exclusively of
no-op statements (`ast.Pass`, or `ast.Expr` with an `ast.Constant`
value — `pass`, `...`, bare strings) with no `ast.Raise` and no
trace-vocabulary call in the handler body. Detection SHALL be AST-only
(no regex). A syntax-error or unreadable file SHALL be a structural
violation (fail-closed), never a pass.

#### Scenario: no-op bodies are counted

- **WHEN** the tree gains an `except OSError: pass` handler under
  scripts/ or hooks/
- **THEN** the owning file's ledger count grows by one and the check
  fails with an `increase` violation

#### Scenario: traced handlers are not counted

- **WHEN** a handler body contains a raise or an emit/log/WARN call
- **THEN** the handler is not counted

#### Scenario: comments do not exempt

- **WHEN** a silent handler carries an explanatory comment
- **THEN** it is still counted (a comment records intent, not a
  runtime trace; the calibrated rule keeps the issue's worst-file
  ranking intact)

### Requirement: Shrink-only ledger

The ledger SHALL ratchet only downward: a count above the ledger fails;
an entry whose count reaches zero SHALL be deleted; a partially cleared
entry SHALL be tightened in the same change; an entry whose file is gone
fails as stale; new debt without an entry fails as unbaselined; debt
with no ledger fails as no-baseline. The ledger lives at
`scripts/silent_except_baseline.yaml` with schema
`silent-except-baseline/1`.

#### Scenario: growth fails

- **WHEN** a file's silent-handler count exceeds its ledger entry
- **THEN** the gate exits 1 with an `increase` violation naming the file

#### Scenario: cleanup tightens

- **WHEN** a batch converts sites to emit/annotate-or-WARN-free traces
  and a count drops but not to zero
- **THEN** the gate fails with `loose-entry` until the entry is
  tightened in the same change; a zero count must delete the entry

### Requirement: CI wiring, smallest surface

The gate SHALL run as one step in the existing lint-hygiene CI job; no
new CI leg SHALL be created. The gate SHALL be fail-loud (exit 0 =
clean, exit 1 = violation; never warn-only).

#### Scenario: gate runs on the release contract job

- **WHEN** the lint-hygiene job executes on a PR
- **THEN** `scripts/silent_except_lint.py` runs against the repo root
  and a growing tree fails the job
