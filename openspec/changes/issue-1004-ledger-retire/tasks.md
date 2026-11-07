# issue-1004-ledger-retire — tasks

## R2a — settlement family

- [x] 1.1 `rlvr/ledger.py`: record/settle append through
      `cl.append(ws, "settlement", row)`; read/fold/settled/
      pending_settlement ride `cl.read(ws, "settlement",
      schema_prefix="rollout-ledger/1")` + the row lint; the module
      flock (`LOCK_REL`, `_locked_append`, `_lock_path`, `_path`)
      retires; fold/settled semantics untouched.
- [x] 1.2 `rlvr/step_grain.py`: `record_attributed_waste` appends
      through `cl.append(ws, "settlement", row)` (`attributed-waste/1`
      stamp unchanged); `WASTE_LEDGER_REL` retires.
- [x] 1.3 `scripts/cost_gate.py`: `append_event` stamps `cost-event/1`
      and appends through `cl.append(ws, "settlement", row)`;
      `load_events` rides `cl.read(ws, "settlement",
      schema_prefix="cost-event/1")`.
- [x] 1.4 `scripts/tuition_curve.py` `cost_state` and `rlvr.state`
      budget-presence read the cost face through the settlement family.
- [x] 1.5 Tests: settlement writers land in runs/settlement.jsonl with
      correct stamps; the retired lock rels are not recreated; the
      rollout ledger byte-prefix invariant still pins.

## R2b — telemetry family

- [x] 2.1 `hooks/dispatch_gate.py`: the strategy-log writer stamps
      `strategy-log/1` and appends through `cl.append(ws, "telemetry",
      row)`; the read-truncate-write cap retires; the
      `_pq_dispatched_before` reader rides `cl.read`.
- [x] 2.2 `rlvr/triples.py`: `_strategy_arm_by_claim` rides
      `cl.read(ws, "telemetry", schema_prefix="strategy-log")`.
- [x] 2.3 `rlvr/prediction_ledger.py`: register/settle append through
      the telemetry family; `read_ledger` rides `cl.read` with the
      `prediction-ledger/1` prefix.
- [x] 2.4 `rlvr/state.py`: `append_snapshot`/`read_situations` ride the
      telemetry family (`situation/1` prefix).
- [x] 2.5 `rlvr/step_ledger.py`: interventions ride the telemetry
      family (`intervention/1` prefix); the legacy-path branch of
      `_append`/`_read` retires (all rels family-routed now).
- [x] 2.6 Tests: telemetry writers land in runs/telemetry.jsonl; the
      triples join sees migrated and fresh dispatch rows.

## R2c — knowledge family

- [x] 3.1 `rlvr/strategy_store.py`: `append_row` /
      `append_workspace_credit_row` append the sealed row through
      `cl.append(ws, "knowledge", row)`; `load_rows` rides `cl.read`
      with the `posterior-store/1` prefix + `trusted_rows` +
      leave-one-out; the holdout filter still precedes the append.
- [x] 3.2 `rlvr/signal_guard.py`: `recent_credits` reads the knowledge
      family, filtered to the calling workspace.
- [x] 3.3 `rlvr/posteriors.py`: record/read ride the knowledge family;
      the module lock retires.
- [x] 3.4 `rlvr/marl.py`: `record_negative`/`read_negatives` ride the
      knowledge family (`marl-negative/1` prefix); `neg_store_path`
      resolves to the family path.
- [x] 3.5 `rlvr/feature_prior.py` + `scripts/feature_mining.py`: the
      table home is the knowledge family file; the miner writes through
      `cl.append` (validated rows); `load_table`/`table_rows` read the
      family.
- [x] 3.6 `rlvr/crystallize.py`: `revoke_claim` rewrites the knowledge
      family file in one pass.
- [x] 3.7 `scripts/eval_split_lint.py`: the store scan face matches the
      knowledge family file name.
- [x] 3.8 Tests: knowledge rows land in knowledge-store.jsonl; the seal
      round-trip holds on an armed workspace; unsealed rows still
      refuse through `trusted_rows`.

## R3 — schema cutover

- [x] 4.1 `scripts/rlvr/consolidated_ledger.py`: delete `LEGACY`,
      `SWITCHED`, `DEFAULT_MIGRATION`, `ARCHIVE_DIR_REL`,
      `legacy_path`, `_legacy_kept`, `_stamp_row`, `_append_verbatim`,
      `migrate`, `_canonical`, `_existing_counts`; drop the
      `include_legacy` parameter and the legacy branch of `read()`.
- [x] 4.2 `REGISTERED` derives from `NATIVE_SCHEMAS` + the
      `WRITER_SCHEMAS` registry the movers declare.
- [x] 4.3 `liveness()` reports all four families from the consolidated
      files only.
- [x] 4.4 `rlvr/disposition_reward.py` + its test: drop the
      `include_legacy=False` call-site argument.
- [x] 4.5 Tests: the core carries none of the retired names; readers
      never open a legacy rel (stale legacy file present → unread).

## R4 — retire CLI

- [x] 5.1 `scripts/consolidate_ledgers.py --retire-legacy`: per family,
      per rel (registry order): stamp-infer, dedupe against the
      consolidated file (idempotent), append, verify counts + stamps,
      then DELETE the legacy rel and its `.<stem>.lock`. NEVER creates
      `runs/archive/`.
- [x] 5.2 `--dry-run` reports without writing; a verify failure keeps
      the legacy rel (exit 3); unknown rels read as absent no-ops.
- [x] 5.3 `scripts/README.md`: the consolidate_ledgers catalog entry
      documents the retire face.

## Verification

- [x] 6.1 New test module `tests/test_ledger_retire_1004.py`: the
      six pins (the five required + the basename repo-scan
      mutation probe) + chronology fixtures.
- [ ] 6.2 `uv run python -m pytest -q` green (full 14k-test
      suite is CI's gate; the affected-suite run is recorded
      in the PR description).
- [x] 6.3 `npx openspec validate issue-1004-ledger-retire` exit 0.
- [x] 6.4 Manifests: `deploy_manifest.py --write` then `--verify`;
      `release_receipt.py --check` if applicable.

## Single-PR closure (one issue = one PR = one branch = one worktree)

- [x] The whole R2a-R4 retirement ships as ONE PR on
      `feat/1004-ledger-retire`, per issue #1004's Staging paragraph
      ("The retirement should be one PR ... plus one workspace migration
      run") and AGENTS.md's one-issue-one-PR rule. The comment's
      "each its own reviewed PR" slice phrasing is NOT used to split the
      PR; the slices describe review order inside one diff.
- [x] The duplicate `feat/1004-r2a-settlement-family` branch/worktree is
      removed so #1004 has exactly one open branch.
- [ ] 1 independent reviewer PASS bound to the staged diff sha256.
- [ ] gate token minted, commit, `gh pr create --base dev`.
- [ ] R5 (real beike workspace migration) — separate operator step after
      the PR lands; issue acceptance #6 stays open until then.
