# Tasks — issue-257-settlement-pq

## 1. Spec + fixture

- [x] Anchor verification (spike line refs vs worktree @ 4c800b5 — all held)
- [x] Commit EXP-3 fixture `tests/fixtures/exp3_delta_h.json` (6dp expected
      values, exact call sequence)

## 2. RED tests

- [x] `tests/test_settlement_pq_257.py` — evidence ΔH 0.069654, eliminate
      ΔH 0.673333 (largest of the sequence), third evidence 0.405198,
      softening −0.185269 (signed) + h_standing_bits separate field,
      ledger round-trip, pq_id == answers_question/target_pq strings,
      KeyError fail-open annotation, settled-PQ guard, idempotent seed,
      pending/no-declaration no-op, registered event word
- [x] Confirmed RED (record_pq_updates absent) before implementation

## 3. Implementation (GREEN)

- [x] `scripts/oracle_runner.py`: `_load_pq_declarations` (tolerant case-YAML
      reader), `ensure_pq` (idempotent get-or-seed from task_spec),
      `apply_pq_event` (snapshot → apply → signed ΔH, D1/D3 guards),
      `record_pq_updates` (orchestration + `pq_posterior_update` events),
      `record_posteriors` drives the PQ face (one ledger save, contract
      otherwise unchanged); module docstring #257 section
- [x] `scripts/event_taxonomy.py`: register `pq_posterior_update` (sorted)

## 4. Tier + manifests

- [x] `tests/_tiers.py`: register `test_settlement_pq_257` in FAST_MODULES
- [x] deploy_manifest --write / --verify (oracle_runner.py,
      event_taxonomy.py are registered scripts)

## 5. Verification (from worktree, pytest -n 8)

- [x] tests/test_posteriors_106.py, test_oracle_runner_108.py,
      test_oracle_cadence_132.py, test_settlement_pq_257.py
- [x] full fast tier
- [x] comment_hygiene_lint
- [x] ruff check (line-length 100)
- [x] openspec validate issue-257-settlement-pq
