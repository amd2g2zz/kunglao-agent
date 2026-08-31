# Tasks — issue #752 hook teleport chain

## 1. SDD

- [x] 1.1 `openspec/changes/issue-752-canonical-chain/proposal.md`
- [x] 1.2 `design.md` — user ruling + D4 durable predicate, D4+ selfcheck independence, D5 scavenger library, D6 upgrade sweep
- [x] 1.3 `tasks.md` (this file)

## 2. D4 — durable-install canonical resolution

- [x] 2.1 RED `tests/test_canonical_chain_752.py`: dev co-install self-path
      wins; repo/worktree falls back to canonical production install;
      canonical path returns itself; e2e wire-up from simulated dev install
      writes dev-root commands with zero stale-install references (RED:
      current two-state code routes the dev case to kunglao-agent)
- [x] 2.2 GREEN `_canonical_hooks_dir` parent-is-skills predicate; gates +
      contract-face grep clean; commit

## 3. D4+ — selfcheck shape-leg independence

- [x] 3.1 RED: mismatch fixture FAILs via default derivation AND when the
      caller lies (`hook_dir=` matching the bad file); register_hooks no
      longer forwards hook_dir; init deploy_hooks resolves its dir from the
      same derivation
- [x] 3.2 GREEN selfcheck_registration internal recompute (+ param kept,
      ignored); hook_activation.register_hooks / kunglao-init call-site
      updates; commit

## 4. D5 — residual-scavenger verifier

- [x] 4.1 RED: mixed-state fixture (`--project OLD` + script NEW) and full
      0.1.2-state fixture — re-wire then all 12 commands at executing root,
      old-root refcount == 0 (grep-level assertion)
- [x] 4.2 GREEN `scripts/install_reference.py` scanner/rewriter +
      `verify_install_references`; commit

## 5. D6 — upgrade end-step sweep

- [x] 5.1 RED: workspace wired to old root → upgrade rewrites settings.json +
      CLAUDE.md to executing root, stderr names each carrier; already-current
      path sweeps too; dry-run prints plan line, zero bytes written; clean
      workspace stays untouched
- [x] 5.2 GREEN upgrade() three integration points + EMIT_ACTIONS additive
      event; commit

## 6. Close-out

- [x] 6.1 Full quality-gate battery (targeted suite, full suite, receipt,
      quality_gates, ruff)
- [ ] 6.2 PR + CI green + auto-merge

## 7. CI trail

- [x] 7.1 PR opened: #766 (feat/752-canonical-chain -> dev); initial push
      created no check-suite (known runner-tolerance case) — this docs
      delta commit re-triggers release-check.
