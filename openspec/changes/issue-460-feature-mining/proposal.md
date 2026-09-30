# Proposal — issue-460-feature-mining (Part A)

## Why

Issue 460's owner direction (2026-09-29/30) reframes anti-thrashing as
predict-before-try: per-instance prediction BEFORE spending an act, the
SATzilla / algorithm-portfolio move. Part A is the data floor under that
move — the (signature features → method/outcome) tuples already exist in
`runs/e2e/*` artifacts (run-state.json, checkpoint/report JSONs, the
workspace audit stream, claim registers, task_spec difficulty blocks,
die/apkid probe outputs, rollout ledgers) across the kunglao-wt
worktrees; nothing mines them into one table. Part B (feature-conditioned
prior on q_cells) cannot be built or A/B-replayed against history that
has no machine-readable shape.

## What changes

- New script `scripts/feature_mining.py`: read-only mining over
  EXPLICITLY-NAMED worktree roots (each `runs/e2e/<run_id>/`), joining
  each run's workspace (task_spec difficulty block, claim register,
  evidence/{die,apkid,difficulty}.json, rollout ledger, audit stream)
  and corpus task.yaml (via run-state `task_dir`), emitting
  `runs/feature-table.jsonl` rows
  `{schema: "feature-table/1", run_id, family, task_id, signature_hash,
  features: {lane, project_type, target_kind, packer_flags,
  difficulty_factors, probe_outputs}, outcomes: [{claim,
  method_family_or_claim_source, act_result, settled, credit}]}`.
- Coverage boundary (disclosed): per-act outcomes come from the
  workspace audit stream; runs predating it (6 of 8 live workspaces)
  mine with empty outcomes — their per-act data survives only in
  checkpoint/report acts[] and a fallback for that face is a declared
  follow-up, not this change.
- Determinism contract: same input set → byte-identical output (sorted
  rows and keys, no wall-clock in rows).
- Sanitized pinned fixtures (3 historical runs) under
  `tests/fixtures/feature-mining-460/` drive the regression tests;
  live process data is never committed.
- Three-registrations discipline for the new script (scripts/README.md
  catalog row → tools/ext-scan.py → deploy_manifest.py --write).

## Non-goals

- Part B is OUT: no prior math, no q_cells change, no
  feature-similarity pooling, no dispatch wiring (later card wave;
  scripts/rlvr/q_cells.py and kernel surfaces are untouched — owned by
  the concurrent #462 agent).
- Part C is OUT: #669 probe-set gating stays exactly as is.
- No live-data commits: kunglao-wt /tmp/e2e trees are read-only mining
  targets; fixtures are sanitized copies.
- No ambient discovery: roots are explicit CLI arguments (the
  compute_priors precedent); no new warn/telemetry surfaces beyond a
  one-line stdout summary and per-run stderr warns.
