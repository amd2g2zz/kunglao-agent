# issue-774-upgrade-transaction — spec delta: upgrade-transaction

## ADDED Requirements

### Requirement: Seven-step upgrade transaction

The migration path of `/kunglao-agent:upgrade` SHALL execute, in order:
(1) the pre-migration git snapshot, (2) outright removal of every
manifest-unknown file in the deployed trees, (3) full manifest deployment
via deploy_workspace_copy, (4) the version migration config items plus the
stamp tail, (5) the hooks_selfcheck verdict on the deployed hook
chain as the outcome gate (the full component table rides the report;
operational rows such as MCP supply and oracle registration never gate
the migration),
(6) a success summary that explicitly tells the operator a session reload
is required, and (7) rollback to the snapshot on any failure in steps
2 through 5.

#### Scenario: steps execute in order

- **WHEN** a behind-stamp workspace is upgraded successfully
- **THEN** the stderr trail carries, in order, the snapshot event, a
  tx-prune event, a tx-deploy event, the migration item events, a
  tx-selfcheck pass event, and the summary event

#### Scenario: reload prompt follows a green gate

- **WHEN** the selfcheck's hook-chain verdict passes
- **THEN** the success summary states that a session reload is required
  for the new deployment to take effect and that hooks are wired but
  dormant until then

### Requirement: Outright prune under a guaranteed anchor

The transaction's prune SHALL remove manifest-unknown deployed files
without a backup step (the snapshot is the safety net), using the same
double-confirm rule as the standalone refresh: a file is removed only when
it is neither a manifest destination nor a newline-normalized byte-variant
of a manifest source. A removed file SHALL remain restorable from the
pre-migration snapshot commit.

#### Scenario: planted unknown file removed

- **WHEN** a manifest-unknown file is planted in a deployed tree and the
  upgrade transaction completes
- **THEN** the file is gone from the working tree and present in the
  snapshot commit

### Requirement: The selfcheck verdict gates the outcome

The selfcheck SHALL run after deploy and config faces and before
the success commit and reload prompt, gating on the hook-chain liveness
verdict (the deployment's own deliverable); a red hook chain SHALL abort
the transaction with the tree rolled back byte-identical to the snapshot
and RC_INCOMPLETE=7, with the repairs attempted first and the failure on
the operator stream.

#### Scenario: deploy failure rolls back byte-identical

- **WHEN** the deploy face raises mid-transaction
- **THEN** the tree rolls back to the snapshot: the working tree digest
  excluding git-ignored runtime dirs is identical pre/post and git status
  is clean

#### Scenario: surviving blocker reds the gate

- **WHEN** a component blocker survives the deploy and config faces
- **THEN** the run exits RC_INCOMPLETE=7, the trail names the selfcheck
  failure and the rollback, and the tree is byte-identical to the snapshot

### Requirement: Sub-faces declare their transaction coverage

The `--wire-up` and `--deploy-local` help text SHALL state exactly which
transaction steps they cover and that the full flow is
`/kunglao-agent:upgrade`.

#### Scenario: help text names the covered steps

- **WHEN** the hook_activation CLI help is rendered
- **THEN** both flags carry a transaction-coverage statement naming their
  steps
