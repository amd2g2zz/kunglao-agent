# T5 digest gate + T5 upgrade chain-hole + init default-flip + T6 lifecycle e2e (#783)

## Why

Phase-1/#789 (manifest + explicit inversion), phase-2/#796 (auto-invert on
copies-present) and T3+T4/#791 (deployed_refresh overwrite + orphan guard)
landed the deployment-inversion mechanics. Three closure gaps remain, all
tracked by the orchestrator takeover comment (2026-08-28):

1. **T5** — nothing records WHAT was deployed into a workspace nor detects
   drift: `check-stale` (#748) compares semver stamps only, so a workspace
   whose framework copies were hand-edited (or deployed by an older skill
   content) passes the gate as `current` and enters the loop with broken
   gates.
2. **T5 chain-hole** — `kunglao_upgrade.upgrade()`'s already-at-version
   early-exit path never runs `_item_deployed_refresh`, so the deploy-drift
   advice ("run /kunglao-agent:upgrade") would spin without effect on a
   current-stamped workspace.
3. **default-flip** — init still registers against the canonical skill
   install; only `--deploy-local` (opt-in) materializes the manifest. The
   user ruling (2026-08-27: "更新和初始化不应该指向全局skill，而是指向工程")
   makes workspace-local the DEFAULT; `--no-hooks` stays the opt-out.

## What Changes

1. `deploy_manifest.manifest_digest(entries)` — THE digest algorithm
   (sha256 over the dest+sha256 entry pairs, dest-sorted, single source for
   every consumer) + `deployed_carrier_path`/`write_carrier` +
   `deploy_drift(ws)` (three-leg drift check) in the same module.
2. Carrier `<ws>/.claude/deployed-manifest.json`
   (`{"schema_version": 1, "deployed_digest": ..., "entries": n,
   "deployed_at": ...}`) written by BOTH deployment faces:
   `hook_activation.deploy_workspace_copy` (init / --deploy-local) and
   `deployed_refresh.refresh` (upgrade).
3. `kunglao.py cmd_check_stale` third criterion: deployed copies present +
   drift → `status="deploy-drift"`, rc=5, advice directs to upgrade.
   Priority: no-stamp > stale(version) > deploy-drift > current.
4. `kunglao_upgrade` early-exit path: when `<ws>/.claude/hooks` exists it
   plans (dry) / applies (real) the deployed-refresh item — behind the SAME
   #753 B1 dirty gate as the main migration path (dirty → RC 6, absent git
   → anchor, clean/skipped → proceed).
5. init default-flip: `deploy_hooks` materializes the manifest (and the
   carrier) BEFORE registration; phase-2 `resolve_deployment` then auto-
   inverts registration to workspace-local. `--no-hooks` skips unchanged.
6. `tests/test_deploy_lifecycle_783.py` — T6 e2e (real init → tamper →
   check-stale deploy-drift → upgrade restores → current) + T5 unit pins.

## Out of scope

- The seven user-data dirs (untouched by every surface above).
- `_gate_stale_workspace` (resume/analysis stderr face) stays semver-only —
  the SKILL.md entry flows through `check-stale`, which carries the new
  criterion.
- Deployment-scope changes (D1 matrix): the manifest set itself is frozen
  here; only its digest witness is added.
