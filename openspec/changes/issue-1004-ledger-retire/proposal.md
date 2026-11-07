# issue-1004-ledger-retire — retire the ledger/data compat window (slices R2a–R4)

## Why

#721 consolidated the ~12 JSONL ledgers into 4 family files but shipped a
compat window: the settlement / telemetry / knowledge families kept
their legacy paths, `read()` dual-reads legacy-then-consolidated, and a
`migrate()` archive face (append + move to `runs/archive/`) waits for
cards that never landed. The adapter shims were already retired by PR
#1021. What remains is the dual-read window, the LEGACY/SWITCHED
registry machinery and the archive migration — compatibility residue.

Owner ruling (no-backcompat policy, 2026-09-01): this repo carries no
old-version compatibility; compatibility residue is removable rung-1.
A reader that still opens a legacy rel is a second source of truth; a
migration that archives bytes into `runs/archive/` is a second home for
data the consolidated file already carries.

## What Changes

1. **R2a — settlement family switches whole**: the rollout ledger
   (`rlvr.ledger` record/settle/read/fold/settled), the attributed-waste
   rows (`rlvr.step_grain.record_attributed_waste`) and the cost events
   (`scripts/cost_gate.py` writer + `scripts/tuition_curve.py` /
   `rlvr.state` budget-presence readers) move to
   `append(ws, "settlement", row)` / `read(ws, "settlement",
   schema_prefix=...)`. The per-module flock/lock rels retire — the
   consolidated append's lock is the single writer guard. Fold/settled
   semantics untouched; rows keep their stamps (`rollout-ledger/1`,
   `attributed-waste/1`); cost rows gain the registered `cost-event/1`
   stamp (unstamped historical rows are stamped at retirement).
2. **R2b — telemetry family switches whole**: the prediction ledger
   (`rlvr.prediction_ledger`), the mainline situation stream
   (`rlvr.state` append_snapshot/read_situations), the interventions
   ledger (`rlvr.step_ledger`), and the strategy dispatch log (writer
   `hooks/dispatch_gate.py`, readers `hooks/dispatch_gate.py` PQ face +
   `rlvr.triples._strategy_arm_by_claim`) move to the telemetry family.
   Strategy-log rows gain the `strategy-log/1` stamp (they carried none
   pre-#1004 — the consolidated append refuses stampless rows); the
   read-truncate-write cap retires with the standalone file (the
   consolidated face is append-only).
3. **R2c — knowledge family switches whole**: the posterior store
   (cross-task `rlvr.strategy_store.append_row/load_rows` AND the
   workspace credit series `append_workspace_credit_row` /
   `rlvr.signal_guard.recent_credits` / the DTS store
   `rlvr.posteriors`), the MARL negative rows (`rlvr.marl`) and the
   feature table (`rlvr.feature_prior` + `scripts/feature_mining.py`)
   move to `knowledge-store.jsonl` under the guarded root. The
   guarded-root resolution stays the single source
   (`strategy_store.store_root`). `sign_row` sealing and the readers'
   `trusted_rows` wall are unchanged — an armed workspace must not start
   refusing its own rows because the file name changed.
   `crystallize.revoke_claim`'s derived-row revocation becomes ONE
   rewrite pass over the knowledge family file (the one sanctioned
   rewrite; the revocation contract is unchanged).
4. **R3 — schema cutover**: `LEGACY`, `SWITCHED`, `DEFAULT_MIGRATION`,
   `ARCHIVE_DIR_REL`, `legacy_path`, the `include_legacy` parameter and
   the legacy branch of `read()` are deleted from
   `scripts/rlvr/consolidated_ledger.py`. `REGISTERED` derives from
   `NATIVE_SCHEMAS` plus the writer stamps each family's movers declare
   (a `WRITER_SCHEMAS` registry). `liveness()` reports all four families
   from the consolidated files only.
5. **R4 — retire CLI**: `scripts/consolidate_ledgers.py --retire-legacy`
   appends each legacy rel's rows to the family's consolidated file
   (chronology: registry rel order, file order within a rel — the order
   the old dual-read produced), verifies row counts + stamps, then
   DELETES the legacy rel and its lock file. `--dry-run` supported;
   idempotent; NEVER creates `runs/archive/`. The legacy rel mapping
   lives in the CLI as the retire face's explicit constants (the only
   sanctioned home for the retired names).
6. **Deliberate exception retained**: `rlvr.disposition.legacy_disposition`
   is a LIVE bridge (session ladder → disposition object), not a compat
   shim — retained and documented as such.

## Impact

- **Affected**: `scripts/rlvr/consolidated_ledger.py`, `rlvr/ledger.py`,
  `rlvr/step_grain.py`, `rlvr/prediction_ledger.py`, `rlvr/state.py`,
  `rlvr/step_ledger.py`, `rlvr/triples.py`, `rlvr/strategy_store.py`,
  `rlvr/posteriors.py`, `rlvr/signal_guard.py`, `rlvr/marl.py`,
  `rlvr/feature_prior.py`, `rlvr/crystallize.py`,
  `rlvr/disposition.py` (doc only), `rlvr/disposition_reward.py`,
  `rlvr/state_signature` shim re-exports; `scripts/cost_gate.py`,
  `scripts/tuition_curve.py`, `scripts/feature_mining.py`,
  `scripts/consolidate_ledgers.py`, `scripts/eval_split_lint.py`
  (store filename face), `scripts/eval_matrix_runner.py` (warm-store
  copy face); `hooks/dispatch_gate.py`.
- **Docs/manifests**: `scripts/README.md` product script catalog
  (consolidate_ledgers entry), release manifests if the file set
  changes (it does not — no files added or removed).
- **Out of scope**: the real beike workspace migration (R5, separate
  orchestrator step); `rlvr.disposition`'s legacy bridge; the
  experience-family writers (already switched in #721).
