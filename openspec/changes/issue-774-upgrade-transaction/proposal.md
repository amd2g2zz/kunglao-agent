# Proposal — issue-774-upgrade-transaction

## Why

Owner contract (2026-10-18, rc2 testing): the upgrade flow must be a
transaction with an exact seven-step shape. Today it is a set of sub-faces:
`--wire-up` registers hooks only, `--deploy-local` copies only, and the
orphan prune lives only inside a version migration item — the owner drove
the sub-faces manually and none did the whole job. The post-deploy
selfcheck existed as a component table but never gated the upgrade
outcome, and a failed deploy left the tree half-migrated.

## What changes

`/kunglao-agent:upgrade` becomes a seven-step transaction on the migration
path (the change is confined to `scripts/kunglao_upgrade.py` orchestration;
every face already exists):

1. git snapshot first (existing pre-migration anchor — unchanged);
2. REMOVE all manifest-unknown kunglao files in the deployed trees,
   outright — the snapshot is the safety net, so the
   `runs/deploy-backup-orphan/` backup step is redundant here
   (`deployed_refresh.prune_outright`, sharing the standalone refresh's
   double-confirm scan);
3. deploy the new files — full manifest copy via `deploy_workspace_copy`
   (fail-loud on manifest/env gaps);
4. update config — the existing version migration items (rewire, ledgers,
   stamps) plus the stamp tail;
5. self-check — hooks_selfcheck runs as the transaction's test face and
   its hook-chain verdict actually gates the outcome (a red chain after
   the repair face raises into the rollback; operational rows ride the
   report without gating);
6. OK — the success summary explicitly tells the operator a session reload
   is required (hooks are wired but dormant until then);
7. failure in steps 2-5 — the tree rolls back byte-identical to the
   snapshot (the existing rollback face extended to the new steps).

Sub-faces keep their names; their `--help` states exactly which transaction
steps they cover. `skills/upgrade/SKILL.md` documents the transaction as
the ONE path.

## Non-goals

- No new exit codes: a transaction failure stays RC_INCOMPLETE=7 with the
  cause on the stderr trail.
- No change to the standalone `deployed_refresh.refresh` semantics (its
  backup face remains for non-transactional callers and pinned tests).
- The already-current fast path keeps its noop contract; the drift-refresh
  branch keeps its own anchor + refresh face.

## Tests

`tests/test_upgrade_transaction_774.py`: step order on the stderr trail;
deploy-failure rollback to a byte-identical tree (digest + git clean);
planted manifest-unknown file removed and restorable from the snapshot
commit; planted broken hook wiring (with an unfixable repair face) reds
the strict selfcheck and rolls back; help text states covered steps;
dry-run lists the transaction faces.
