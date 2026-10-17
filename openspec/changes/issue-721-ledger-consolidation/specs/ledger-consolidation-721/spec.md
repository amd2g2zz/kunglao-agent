# ledger-consolidation-721 delta — issue-721-ledger-consolidation

## ADDED Requirements

### Requirement: Four consolidated ledger files by lifecycle

The system SHALL consolidate the pre-#721 JSONL stores into four files:
`runs/experience.jsonl` (WHAT HAPPENED), `runs/settlement.jsonl` (HOW IT
CLOSED), `runs/telemetry.jsonl` (WHAT WAS OBSERVED), and
`knowledge-store.jsonl` under the guarded cross-task root
(`strategy_store.store_root()`). A family SHALL switch whole (writers +
readers together); a family that has not switched SHALL keep its legacy
paths untouched.

#### Scenario: the experience family writes the consolidated file

- **WHEN** a transition settles, a dispatch observation records, or a
  step/evidence row appends (the switched family)
- **THEN** the row lands in runs/experience.jsonl carrying its
  `<name>/N` schema stamp, and no writer appends to
  runs/transitions.jsonl, runs/q-cell-log.jsonl, runs/step-ledger.jsonl,
  or runs/evidence-credit.jsonl

#### Scenario: an unswitched family is untouched

- **WHEN** the rollout ledger or the situation stream records (families
  still on their own cards)
- **THEN** their rows land on the legacy paths exactly as before #721

### Requirement: Row contracts are enforced in the consolidation core

`append()` SHALL be append-only and flock-guarded, and SHALL REFUSE —
ONE warn, never a raise — a row whose `schema` is not a non-empty,
whitespace-free string, a non-dict row, an unknown family, or a
non-serializable row. Every row already in a consolidated file SHALL
carry a schema stamp. Existing stamp names/versions SHALL NOT change;
transition rows SHALL gain the new `transition/1` stamp (they carried
none pre-#721).

#### Scenario: a stampless append is refused

- **WHEN** a caller appends a row without a schema stamp
- **THEN** append returns False, ONE warn names the attribution
  contract, and the file is byte-unchanged

#### Scenario: a multi-schema read filters by stamp

- **WHEN** a consumer reads the consolidated file through a schema
  prefix ("transition", "step-record", "q-cell-obs", or a tuple)
- **THEN** only matching-stamp rows return, and an unstamped legacy
  archive row returns only through its own rel's registered stamp
  prefix — never another schema's read

### Requirement: Migration appends, never rewrites; originals are archived

The one-time migration SHALL append every legacy row into the family's
consolidated file (values preserved; a missing stamp added ONLY when the
rel registers exactly one schema — a multi-schema rel's unstamped row
copies verbatim, never a guessed stamp), then MOVE the original into
`runs/archive/` with bytes intact. Re-running SHALL append nothing
already copied (canonical-JSON multiset idempotence). A failed append
SHALL leave the rel unarchived (re-run retries). No path SHALL rewrite,
truncate, or delete a legacy file.

#### Scenario: history survives the migration byte-identically

- **WHEN** `migrate(ws)` runs on a workspace with populated legacy rels
- **THEN** each originals' bytes are archived under runs/archive/
  identical, the legacy path no longer exists, the consolidated file
  gains every row (relative order preserved per schema), and a second
  run appends nothing

#### Scenario: dry-run writes nothing

- **WHEN** the CLI runs with `--dry-run`
- **THEN** the report lists rows/appends and no file is created,
  moved, or modified

### Requirement: Readers accept both paths during the compat window

Every consumer of a migrated store SHALL read through the consolidated
read face: legacy archive rows first (if the rel still exists), then the
consolidated file's rows under the requested stamp filter. A direct
path read of a migrated rel SHALL NOT remain on a production read path
— the only permitted exception is a documented partial-deploy fallback
(an ImportError guard whose body IS the legacy read, taken only when
the rlvr core is absent). The
fold (`q_cells.fold` via its store) SHALL read observations from the
consolidated file through the `q-cell-obs` stamp filter with the legacy
fallback.

#### Scenario: a workspace mid-migration still reads its history

- **WHEN** the legacy rel is present and the consolidated file has new
  rows (migration not yet run)
- **THEN** reads return the legacy rows first, then the new rows, and a
  reader with a schema filter never mixes other schemas in

### Requirement: Per-schema liveness counters are visible

`liveness(ws)` (and the CLI `--liveness`) SHALL report a count for every
registered schema of every family — a registered-but-dead schema reports
0 (visible, never silently absent) — plus foreign stamps and unstamped
rows under their own keys.

#### Scenario: a dead schema is an alarm, not silence

- **WHEN** a workspace has q-cell observations but no credit amendments
- **THEN** the liveness face reports experience:q-cell-obs/1 > 0 and
  experience:credit-amendment/1 == 0

### Requirement: The consolidated learning feed is closed to blind acts

Because the q-cell arm values ride `runs/experience.jsonl`, the
blind-act walls SHALL extend to it: `hooks/rt_read_barrier.py` SHALL
deny the file on every read face (Read targets, Bash path tokens,
Glob/Grep patterns), and `scripts/rlvr/settlement_scorer.py` SHALL
refuse it as an artifact at the door. The move SHALL NOT unblind any
act.

#### Scenario: a settler read of the consolidated feed is rejected

- **WHEN** a settler/RT act reads (or greps, or cats) runs/experience.jsonl
- **THEN** the barrier rejects with REJECT rt_read_barrier, and
  settler_input refuses the path with "excluded" before any read

### Requirement: The migration CLI reports honestly

`scripts/consolidate_ledgers.py <ws>` SHALL migrate the switched
families by default (`--families` narrows; `--dry-run` reports only),
print per-rel status (absent|dry-run|migrated|partial|
copied-unarchived), and exit 3 when any rel ended partial or
copied-unarchived — nothing rewritten, nothing deleted, re-run safe.

#### Scenario: a partial rel fails loudly

- **WHEN** an append refusal leaves a rel unarchived
- **THEN** the CLI reports status=partial for that rel and exits 3,
  while every other rel completes normally
