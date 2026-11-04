# tasks — issue-774-upgrade-transaction

- [x] 1. RED: tests/test_upgrade_transaction_774.py — step-order trail,
      deploy-failure rollback (byte-identical digest + clean git status),
      outright prune restorable from the snapshot commit, planted broken
      hook wiring reds the strict gate and rolls back, help-text coverage
      statements, dry-run transaction faces.
- [x] 2. deployed_refresh: extract the shared _scan_orphans helper; add
      prune_outright (unlinks, no backup, raises into the transaction).
- [x] 3. kunglao_upgrade: seat steps 2/3 inside the items try (with
      tx-prune/tx-deploy ok+fail events), step 5 (hooks_selfcheck --strict,
      TxSelfcheckFailure) inside the tail try before the success commit,
      step 6 reload-required wording; dry-run prints the transaction faces;
      module docstring documents the seven-step shape.
- [x] 4. hook_activation: --wire-up / --deploy-local help states the
      covered transaction steps.
- [x] 5. skills/upgrade/SKILL.md: the transaction is the documented path;
      rc 7 wording covers the selfcheck gate.
- [x] 6. Hygiene trio: lint baselines green, deploy-manifest regenerated
      and verified (script sha256 churn), ext index unchanged (no new file).
- [x] 7. openspec validate green; full targeted suite green.
