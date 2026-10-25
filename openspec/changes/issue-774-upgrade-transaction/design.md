# design — issue-774-upgrade-transaction

## Verified anchors (worktree feat/774-upgrade-transaction @ dev b9a4a802)

| Question | Actual | Drift |
|---|---|---|
| Does upgrade run the selfcheck today? | No call site in kunglao_upgrade; the strict face exists (hooks_selfcheck main_with_ws strict=True) and its docstring already claims the init/upgrade closure face | the claim was aspirational — this change implements it |
| Where does the orphan prune live? | Only inside deployed_refresh.refresh (backup-then-remove), called by the 0.1.4/0.1.6 migration items | matches the issue's sub-face trap |
| Rollback coverage | _rollback_failed covers the items try and the tail try; prune/deploy/selfcheck had no seat in either | covered by seating the new steps inside the existing guarded regions |

## The seven-step mapping

| Step | Face | Guard |
|---|---|---|
| 1 | _snapshot_pre_migration (unchanged) | refuse-no-snapshot stays absolute |
| 2 | deployed_refresh.prune_outright (new; shared _scan_orphans) | inside the items try -> rollback, RC 7 |
| 3 | hook_activation.deploy_workspace_copy (existing, fail-loud) | inside the items try -> rollback, RC 7 |
| 4 | plan items + stamp tail (unchanged faces) | existing guards |
| 5 | hooks_selfcheck.main_with_ws(strict=False) — the hook-chain verdict gates; the full table rides the report | TxSelfcheckFailure -> rollback, RC 7 |
| 6 | reload prompt (pinned phrase kept, reload-required line added) | after the gate |
| 7 | _rollback_failed (unchanged) | snap_sha absolute |

## Findings during build (each pinned by test)

1. **Nested deployed roots double-visit orphans.** A manifest declaring
   dests at `.claude/templates` AND `.claude/templates/state` makes each
   orphan rglob-visited once per covering root: the standalone refresh's
   old inline loop degraded to a WARN detail on the second (missing)
   visit, while the fail-loud outright prune surfaced it as a crash.
   Fixed in the shared `_scan_orphans` (dedupe by rel path) + unlink
   `missing_ok` — a latent refresh bug paid down by the transaction.
2. **Anchor bookkeeping is not payload.** The step-1 bootstrap writes
   `.gitignore` (committed INSIDE the snapshot) — a rollback restores it,
   so byte-identical assertions measure the tree minus `.git/`, `runs/`
   and `.gitignore` (the git-level truth — clean status — is the
   primary check).
3. **Iron digest needs the selfcheck report exemption.** Step 5 writes
   `runs/.hooks-selfcheck.json` (every selfcheck tick writes it too);
   added to the framework-owned exemption list (same class as
   `runs/.init-report.json`), otherwise the transaction fails its own
   iron rule on its own telemetry.

## Decisions

1. **Prune deletes outright.** The standalone refresh keeps its
   backup-then-remove face; the transaction uses a sibling
   `prune_outright` that shares `_scan_orphans` (same double-confirm rule:
   neither a manifest destination nor a newline-normalized variant) and
   unlinks without a backup. The git snapshot is the only safety net, per
   the owner contract. Manifest-unbuildable raises into the rollback —
   guessing "unknown" without a manifest is the one unrecoverable shape.
2. **The selfcheck gate bites on the hook-chain verdict.** The
   transaction runs the full hooks_selfcheck face (repairs + component
   table + persisted report), and gates on its exit verdict — the
   HOOK-CHAIN liveness face, i.e. the deployment's own deliverable. A
   wiring still red after the repair face rolls the transaction back.
   The operational rows (MCP supply, oracle registration, scheduler,
   ledger) ride the output without gating: they are operator supply
   state, not deployment state — a legacy workspace may legitimately
   lack them, and gating on them would make the upgrade uncompletable
   until unrelated supply is fixed (verified against the neighbor
   suites: the full-strict gate reds 19 pinned upgrade tests on
   workspaces without MCP/oracle registration). This is also the shape
   the acceptance names: the failure path is exercised by a planted
   broken HOOK. A red deployment never prints the reload prompt.
3. **Exit code unchanged.** A gated rollback is RC_INCOMPLETE=7; the
   stderr carries `tx-selfcheck fail` / `tx-deploy fail` / `tx-prune fail`
   events plus the existing rollback event, so the trail names the failed
   step without a new rc.
4. **Ledger vocabulary untouched.** The transaction faces emit the
   existing `upgrade_item` / `upgrade_rollback` actions (detail strings
   distinguish); the new names live only on the free-form stderr trail
   (`tx-prune`, `tx-deploy`, `tx-selfcheck`).
5. **Iron rule unaffected.** Steps 2-3 write only `.claude/` (framework);
   the selfcheck's own writes (repairs, runs/.hooks-selfcheck.json) land
   in the tail, after the pre/post digest check, exactly like the
   statusline heal today.
