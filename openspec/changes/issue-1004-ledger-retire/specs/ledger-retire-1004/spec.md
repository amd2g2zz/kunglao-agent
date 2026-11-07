# ledger-retire-1004 delta — issue-1004-ledger-retire

## ADDED Requirements

### Requirement: One consolidated file per family — no dual read

Each family's rows SHALL have ONE home: the four family files
(`runs/experience.jsonl`, `runs/settlement.jsonl`, `runs/telemetry.jsonl`,
`knowledge-store.jsonl` under the guarded cross-task root).
`consolidated_ledger.read()` SHALL return consolidated rows only — the
`include_legacy` parameter and the legacy branch SHALL NOT exist — and
no production module under `scripts/` or `hooks/` SHALL read or write a
legacy rel. Every family SHALL have switched whole: settlement
(rollout ledger, attributed waste, cost events), telemetry
(predictions, situations, interventions, the strategy dispatch log),
knowledge (posterior store cross-task + workspace credit series, MARL
negatives, feature table).

#### Scenario: a stale legacy file is never read

- **WHEN** a workspace carries a pre-migration legacy rel (e.g.
  `runs/rollout-ledger.jsonl`) beside the consolidated file
- **THEN** `read(ws, "settlement", schema_prefix="rollout-ledger/1")`
  returns only the consolidated file's rows — the legacy bytes are
  invisible until the retire CLI moves them

#### Scenario: the settlement family writes the consolidated file

- **WHEN** the rollout ledger records or settles, attributed waste is
  priced, or a cost event appends
- **THEN** the row lands in runs/settlement.jsonl carrying its
  registered stamp (`rollout-ledger/1`, `attributed-waste/1`,
  `cost-event/1`) and no writer appends to `runs/rollout-ledger.jsonl`,
  `runs/attributed-waste.jsonl`, or `cost_events.jsonl`

#### Scenario: the telemetry family writes the consolidated file

- **WHEN** a prediction registers or settles, a situation snapshot
  appends, an intervention records, or the dispatch gate logs a
  strategy dispatch
- **THEN** the row lands in runs/telemetry.jsonl carrying its stamp
  (`prediction-ledger/1`, `situation/1`, `intervention/1`,
  `strategy-log/1`)

#### Scenario: the knowledge family writes the consolidated file

- **WHEN** a posterior-store row (cross-task or workspace credit
  series), a MARL negative row, or a feature-table row appends
- **THEN** the row lands in `knowledge-store.jsonl` under the guarded
  root (`strategy_store.store_root()` — the single source), carrying
  its stamp

### Requirement: Row contracts and the single writer guard are unchanged

The consolidated `append()` SHALL remain append-only, flock-guarded by
the family file's own `.<stem>.lock`, and refuse a stampless row (ONE
warn, never a raise). The retired modules' per-module lock rels SHALL NOT be
recreated — the consolidated append's lock is the only writer guard on
the moved paths, with no nested locks. Rows SHALL keep their existing
stamps; cost rows and strategy-log rows SHALL gain `cost-event/1` and
`strategy-log/1` (the only structural additions).

#### Scenario: fold/settled semantics ride the family file

- **WHEN** the rollout ledger folds, queries settled rows, or replays
  its byte-prefix invariant on the consolidated file
- **THEN** identity/signals/settlement fold semantics, the reward-rail
  lint and the append-only byte prefix behave exactly as before — only
  the home file changed

#### Scenario: no nested locks on a moved path

- **WHEN** any moved writer appends
- **THEN** exactly one lock is taken (the consolidated append's); the
  retired `runs/.rollout-ledger.lock` /
  `runs/.posterior-store.lock` rels are never touched

### Requirement: The seal wall rides the family move

Sealed writers SHALL keep sealing and readers SHALL keep the trust
wall: writers that seal (`sign_row` before append) keep sealing, and
the knowledge readers keep the `trusted_rows` wall. an armed
workspace SHALL NOT start refusing its own rows because the file name
changed, and unsealed rows SHALL still refuse through the read faces.

#### Scenario: seal round-trip through the new face

- **WHEN** an armed workspace appends a posterior-store row through
  `strategy_store.append_store_row` and reads it back through
  `load_rows`
- **THEN** the row is `trusted_rows`-valid (the seal verifies against
  the same key and run-head), and a forged row appended beside it is
  refused

### Requirement: Chronology is preserved by the retire CLI

The retire CLI SHALL append each legacy rel's rows
(`scripts/consolidate_ledgers.py --retire-legacy`) to the family's consolidated file
in the order the old dual-read produced them (registry rel order, file order within a
rel), verify the row counts and stamps, then DELETE the legacy rel and
its lock file. The CLI SHALL be idempotent, SHALL support `--dry-run`
(writes and deletes nothing), and SHALL NEVER create `runs/archive/`. A
verify failure SHALL keep the legacy rel (exit 3).

#### Scenario: every legacy rel retires through the CLI

- **WHEN** a fixture workspace carrying EVERY legacy rel (stamped and
  unstamped rows) runs `--retire-legacy`
- **THEN** every legacy rel and its lock file are deleted, every row is
  readable from the consolidated files with the correct stamps in
  dual-read order, a second run is a no-op, and no `runs/archive/`
  directory exists

#### Scenario: dry run writes nothing

- **WHEN** `--retire-legacy --dry-run` runs on the same fixture
- **THEN** the report names the rows that would move, and no
  consolidated file is created or appended and no legacy rel is deleted

### Requirement: The core registry carries no compat machinery

The consolidation core (`scripts/rlvr/consolidated_ledger.py`) SHALL
NOT define `LEGACY`, `SWITCHED`, `DEFAULT_MIGRATION`,
`ARCHIVE_DIR_REL`, or any `include_legacy` parameter. `REGISTERED` SHALL derive from
`NATIVE_SCHEMAS` plus the writer stamps each family's movers declare,
and `liveness()` SHALL report every registered schema across all four
families from the consolidated files only (a dead schema reads 0,
never silently absent). The retired rel names SHALL appear only in the
retire CLI's explicit constants. `rlvr.disposition.legacy_disposition`
SHALL be retained and documented as a LIVE bridge (session ladder →
disposition object), not a compat shim.

#### Scenario: liveness over the four families

- **WHEN** `liveness(ws)` runs on a workspace with rows in each family
  file
- **THEN** every registered schema reports its consolidated-file count,
  dead registered schemas report 0, and no legacy rel contributes

#### Scenario: the retired names are gone from the core

- **WHEN** the repo scan inspects scripts/rlvr/consolidated_ledger.py
- **THEN** none of `LEGACY`, `SWITCHED`, `DEFAULT_MIGRATION`,
  `ARCHIVE_DIR_REL`, `include_legacy` appears in it
