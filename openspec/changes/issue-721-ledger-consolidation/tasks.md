# tasks — issue-721-ledger-consolidation

## 1. The consolidation core

- [x] `scripts/rlvr/consolidated_ledger.py`: CONSOLIDATED + LEGACY +
      REGISTERED registries (14 rels, 4 families; knowledge under the
      guarded root), `append()` (flock, append-only, stampless-row
      refusal — ONE warn, never a raise; non-serializable rows refused
      too), `read()` (legacy-first ordering, stamp filter str|tuple,
      unknown-family fail-open), `liveness()` (registered schemas at 0 +
      observed + `(no-schema)`), `migrate()` (append → move archive,
      multiset-idempotent, dry-run)
- [x] review hardening (t5-721-core F1-F3): TypeError/ValueError on a
      non-serializable row → refuse; `read(unknown)` → [] + warn;
      non-string / unstripped / blank stamps refused
- [x] `tests/test_ledger_consolidation_721.py`: pin 1 (stamps + refusal
      + concurrent-append well-formedness), pin 2 (append-only migration
      incl. re-run idempotence, dry-run, no-guessed-stamp), pin 3
      (both-path compat reads + filter), pin 4 (per-schema liveness),
      knowledge-root pin, CLI pin

## 2. Writer migration — the experience family (switched whole)

- [x] `rlvr/incremental_reward.py`: `transition/1` stamp on new rows;
      writer targets `runs/experience.jsonl`; `read_transitions` rides
      the consolidated read face (legacy archive first)
- [x] `rlvr/q_cells.py`: `append_observation` targets the consolidated
      file; `JSONLQStore.observations()` = stamp-filtered read face
      (the fold's read); `reindex` scans both filenames, legacy group
      first, stamp-filtered
- [x] `rlvr/step_ledger.py`: step-record + evidence-credit writers
      target the consolidated file; `_read` stamp-filters per rel
      (`step-record`; `evidence-item`+`credit-amendment`);
      interventions stay legacy (telemetry family, its own card)

## 3. Consumers + walls

- [x] direct-path consumers switched to the read faces:
      `scripts/rollup.py`, `scripts/eval_loop_runner.py`,
      `scripts/eval_matrix_report.py`, `scripts/e2e/runtime.py`
      (`_prior_claim_ids` — the 1-F10 wipe guard never silently empties)
- [x] `rlvr/censored_review.py`: matches `transitions.jsonl` AND
      `experience.jsonl`, skips `runs/archive/`, filters non-transition
      rows from the consolidated file without inflating malformed counts
- [x] `hooks/rt_read_barrier.py` + `rlvr/settlement_scorer.py`:
      `runs/experience.jsonl` joins the blind-act deny lists (READ /
      Bash tokens / Glob-Grep patterns / doc-side excluded files)
- [x] affected suites updated to the read faces (no direct-path reads of
      migrated files remain in tests)

## 4. Migration CLI

- [x] `scripts/consolidate_ledgers.py`: `<ws>` (migrate; `--dry-run`,
      `--families`, `--json`), `--liveness` (per-schema counts); exit
      3 on partial/copied-unarchived (nothing rewritten or deleted)
- [x] registrations: `scripts/README.md` row (declaration scan),
      deploy-manifest re-mint

## 5. OpenSpec + docs

- [x] this change dir (proposal / design / tasks / spec delta)
- [x] `scripts/rlvr/README.md` package tree row; affected module
      docstrings updated to the #721 homes

## Follow-ups (NOT delivered in this change — recorded for their cards)

Each family switches WHOLE (writers + readers + consumers + tests
together), then migrates with
`consolidate_ledgers.py <ws> --families <family>`:

- [ ] **settlement family** — `runs/settlement.jsonl`:
      `rlvr/ledger.py` (rollout-ledger; its own flock already),
      `rlvr/step_grain.py` (attributed-waste), `cost_events.jsonl`
      (written by `scripts/cost_gate.py`, workspace-root-relative, rows
      UNSTAMPED `{ts,amount,source}` — the card must add a
      `cost-event/1` stamp); readers: `mission_ledger`,
      `rho_verifier`, `tuition_curve`, `ledger.settled/fold` consumers
      (priors/compose/triples), `state.py` cost-events presence face;
      REGISTRY entry exists in `consolidated_ledger.LEGACY` already
- [ ] **telemetry family** — `runs/telemetry.jsonl`:
      interventions (`rlvr/step_ledger.record_intervention`),
      predictions (`rlvr/prediction_ledger.py`), situation-stream
      (`rlvr/state.py` append_snapshot/read_situations), strategy-log
      (written by `hooks/dispatch_gate.py`; read by `rlvr/triples.py`
      and `hooks/dispatch_gate.py`'s own read path; rows unstamped
      `event=…` — the card must add a stamp or a documented
      legacy-unstamped exception)
- [ ] **knowledge family** — `knowledge-store.jsonl` under the guarded
      root: cross-task posterior-store (`rlvr/strategy_store.py` write
      face = e2e settlement hook; read face = warm_pools),
      marl-negative (`rlvr/marl.py`), feature-table
      (`rlvr/feature_prior.py` + `scripts/feature_mining.py` — note:
      historically workspace-scoped `runs/feature-table.jsonl`, NOT the
      cross-task root; the card must decide the resolution face)
- [ ] the per-workspace `runs/posterior-store.jsonl` (#428 bank) is NOT
      in the 4-file cut — recorded as out of scope (its own design
      decision if ever consolidated)
