# Design — #783 T5/T6/default-flip

Branch base: origin/dev `e4784a4`. Anchors verified in-repo (hook_activation
`deploy_workspace_copy` / `resolve_deployment`, deployed_refresh.refresh,
kunglao.py `cmd_check_stale`, kunglao_upgrade.upgrade early-exit, kunglao-init
`deploy_hooks`).

## D1 Digest single source + carrier

`deploy_manifest.manifest_digest(entries)` = sha256 over, in dest-sorted
order, the UTF-8 concatenation of `dest` + `sha256` per entry. Every
consumer calls this ONE function; nobody re-rolls a hash walk.

Entries source decision — **`build_entries()` recompute** is the runtime
authority:

- `deploy-manifest.yaml` stays the audited D1 contract (committed artifact,
  `--write` regenerated, `--verify` CI-gated: yaml == build_entries). The
  equivalence `manifest_digest(build_entries()) == manifest_digest(yaml
  files)` is pinned by a unit test, so both readings agree on any green
  repo.
- Rationale against "skill-side reads the yaml": `deployed_refresh` deploys
  TREE bytes; stamping it with a yaml-derived digest would make a stale-yaml
  repo cycle forever (refresh rewrites bytes+carrier, check still fails).
  With build_entries as authority, every path converges: after upgrade,
  bytes == build_entries == carrier == expected.

Carrier `<ws>/.claude/deployed-manifest.json`:

```json
{"schema_version": 1, "deployed_digest": "<sha256>",
 "entries": 42, "deployed_at": "2026-08-28T12:00:00Z"}
```

Writers (both call `deploy_manifest.write_carrier`):
- `hook_activation.deploy_workspace_copy` — after the copy loop (carrier
  digest = build_entries; report gains `digest`).
- `deployed_refresh.refresh` — after overwrite + orphan guard, non-dry only
  (detail gains `carrier=<8hex>`; WARN-only posture preserved — write
  failures surface through `item()`'s existing try).

## D2 check-stale third criterion — three-leg drift

`deploy_manifest.deploy_drift(ws)` (kunglao.py stays a thin consumer).
Gate precondition: `<ws>/.claude/hooks` is a directory (phase-2 "copies
present" semantics — legacy workspaces never enter the criterion).

Legs, all must hold else drift:
1. **carrier-present** — missing/unparseable carrier → drift
   (`carrier-missing`): instructed behavior; upgrade rewrites it.
2. **carrier-fresh** — `carrier.deployed_digest == expected` where
   `expected = manifest_digest(build_entries())` → catches "skill package
   content moved since deploy" at unchanged semver (the semver leg cannot
   see same-version content drift; dev checkouts hit this daily).
3. **bytes-fresh** — digest recomputed over the workspace's ACTUAL deployed
   files (CRLF-normalized via `deploy_manifest._sha`, same as manifest shas;
   any missing dest ⇒ drift) == expected → catches hand-tampering.

Leg 3 is what makes the T6 e2e tamper case observable; legs 1+2 are what
make the carrier load-bearing rather than decorative. The orchestrator
instruction names carrier-vs-skill as the comparison; the tamper e2e
(mandated in the same instruction) is only satisfiable with the bytes leg,
so the check is the union — recorded here as the design adjudication.

Priority in `cmd_check_stale`: no-stamp > stale(version) > deploy-drift >
current. Version-stale wins on purpose: a version upgrade naturally
overwrites the copies, so reporting stale first sends the user to the same
fix with the broader remedy. Envelope: `status="deploy-drift"`, rc=5
(RC_STALE_WORKSPACE), advice
`run /kunglao-agent:upgrade <ws> first (framework copies drifted)`, plus
diagnostic fields `drift_reason` / `deployed_digest` / `skill_manifest_digest`.

## D3 upgrade early-exit chain-hole — full gate parity

`upgrade()` already-at-version branch (origin >= target AND plan empty):
when `<ws>/.claude/hooks` exists —

- dry-run: list `_item_deployed_refresh(ws, dry=True)` in the plan (noop),
  no gate, no writes (mirrors main-path dry-run posture).
- real run: the SAME #753 B1 gate block as the main path (dirty → structured
  refusal RC_DIRTY_WORKSPACE=6 with commit/stash guidance; absent git →
  `ensure_pre_upgrade_anchor`; skipped probe → loud WARN + proceed; clean →
  proceed), then refresh item reported into stdout + `upgrade_item` events +
  items_out. Anchor-created runs land a post-state commit so the tree ends
  clean (same promise as the main path); clean-owned-repo runs leave the
  refresh uncommitted — posture parity with the main migration path, which
  also does not commit for a clean owned repo.

Gate block extracted into `_refuse_dirty(ws, dirty_n)` shared by both paths
(byte-identical stderr, pinned by #753's guidance assertions). Refinement
(full-suite finding): the item ACTIVATES only when
`deploy_manifest.deploy_drift(ws)` reports actual drift (`_deploy_drift_now`
— unreadable probes fail towards doing the work); the no-drift case stays
the historic true noop (rc 0, no item, no gate) that #726's
`test_already_current_is_noop` pins. The dirty-refusal therefore fires only
when a write is genuinely required. `--json`
envelope: a hooks-present early-exit now reports status "ok" with the
refresh item (items_out non-empty); "already-current" remains the status for
workspaces without deployed copies — no pinned test touches that combo.

## D4 init default-flip

`deploy_hooks` calls `hook_activation.deploy_workspace_copy(ws)` BEFORE any
registration, unconditionally (its caller `deploy_env` already routes
`--no-hooks`/plugin_mode away — opt-out semantics unchanged and pinned).
Registration then flows through the existing chain:
`deploy_hooks._patch_settings` writes the canonical-shape bootstrap entries
(selfcheck still passes — copies do not change what IT asserts), and
`bootstrap_observability` → `register_hooks(workspace=ws)` hits phase-2
`resolve_deployment` → copies present → ALL registry entries rewritten to
`uv run --project <ws> <ws>/.claude/hooks/<name>.py` with the deployed-mode
selfcheck. No change needed in bootstrap_observability.

Report shape: `deploy_hooks` gains
`"deployed_manifest": {"entries": n, "digest": "<sha256>"}` (the
`_deploy_agents` component-record style). The env-manifest ledger
(`components`) is NOT extended — its shape is pinned elsewhere and the
carrier on disk is the durable record.

Guard-test surface swept (see tasks.md §4): the four phase-2 pins
(`test_deploy_inversion_783`) construct workspaces directly, and
`test_no_local_copies_falls_back_canonical` builds a bare `.claude/` without
running init — verified unaffected; any test asserting the OLD canonical
command shape on init-produced settings.json gets synced.

## D5 T6 e2e environment contract

Real `kunglao-init.py <ws> --type linux --skip-toolchain --assume-yes` with
`bins/` placeholder sample, subprocess under `_run_cli`-shaped env hygiene
(#794): scrub `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`, force PYTHONUTF8/
PYTHONIOENCODING, utf-8/replace capture. `KUNGLAO_UPGRADE_NO_UV_SYNC=1` on
the upgrade leg (offline determinism, same fixture posture as
test_deploy_surface_755). Init's #739 final-step git init + commit makes the
post-init workspace git-clean, which is exactly what the upgrade leg's B1
gate requires.

## D6 Field finding: #791 backup face vs #726 iron rule (fixed here)

The T6 e2e exposed a pre-existing internal contradiction: the #791
deployed_refresh backs locally-modified copies up under
`runs/deploy-backup-<ts>/` (and `runs/deploy-backup-orphan/`), but `runs/`
is one of the seven #726 iron-rule user-data dirs — so ANY real
drift-repair upgrade through `kunglao_upgrade` aborted RC=4
(iron-rule violation) on the framework's own forensics write. #791's tests
exercised `refresh()` directly, never through the migration driver, so the
conflict was invisible until the e2e.

Fix: `_is_exempt` gains the D4-class exemption
`rel.startswith("runs/deploy-backup-")` — the same pattern already used for
`runs/upgrade-snapshot.*.json` (framework-owned forensics). Analysis data
under runs/ (worker status, logs, artifacts) stays byte-protected; pinned
by `test_deploy_backup_dirs_are_iron_rule_exempt` plus the e2e itself
(tamper -> upgrade CLI -> rc 0).
