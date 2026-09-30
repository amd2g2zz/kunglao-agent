# tasks — issue-467-deploy-numpy

## 1. RED (TDD — tests first)

- [x] 1.1 tests/test_dep_surface_gate_467.py (fast tier, registered in
  tests/_tiers.py FAST_MODULES): fixture package importing numpy at
  module level with a numpy-less pyproject -> check() reports missing
  numpy, ok=False; CLI exits 1.
- [x] 1.2 fast: the repo's own package passes (ok=True; hard set
  covered; guarded-undeclared listed as info only).
- [x] 1.3 fast: guarded exemption — a try/except ImportError import of
  an undeclared module is NOT missing (listed in guarded_undeclared).
- [x] 1.4 fast: name mapping — `import yaml` is covered by a
  `PyYAML>=6.0` declaration; `z3` by `z3-solver`; case/underscore
  normalization.
- [x] 1.5 fast: env-root coverage semantics — surface importing numpy,
  env pyproject without numpy -> missing; same env with numpy -> ok
  (the #467 mixed-drift replay).
- [x] 1.6 fast: deploy refusal — deploy_workspace_copy on a workspace
  with a monkeypatched env root lacking numpy raises RuntimeError
  naming numpy + the env root + the remediation, BEFORE any copy (no
  .claude/deployed-manifest.json carrier written).
- [x] 1.7 fast: deploy green path — consistent roots deploy unchanged
  (return shape untouched).
- [x] 1.8 fast: deployed_refresh posture — a gap surfaces as a warn
  detail (return string carries dep_gap), never raises.

## 2. GREEN

- [x] 2.1 scripts/dep_surface_gate.py: norm_dist / IMPORT_DIST_ALIASES /
  hard_imports (AST, guarded-exempt, stdlib+in-tree exempt) /
  declared_deps (instrument_menu parse reuse, tolerant fallback) /
  check(surface_root, env_root=None) / CLI (--surface, --env, --json;
  default repo self-check; exit 1 on missing).
- [x] 2.2 hook_activation.deploy_workspace_copy: gate call before the
  copy loop; RuntimeError on missing; env root = _framework_project_root()
  (same resolution as build_hook_entry — single source); None env root ->
  canonical warn + proceed.
- [x] 2.3 deployed_refresh.refresh: gate call; gap -> kunglao_log warn
  + dep_gap part in the returned detail (never raises).

## 3. CI + registration

- [x] 3.1 .github/workflows/release-check.yml lint-hygiene leg: new step
  running the repo self-check gate (exit-gating).
- [x] 3.2 scripts/README.md: catalog row for dep_surface_gate.py.
- [x] 3.3 deploy-manifest.yaml regenerate (scripts/deploy_manifest.py
  --write) AFTER all content edits (ordering trap: content -> catalogs
  -> comment-hygiene emit -> manifest --write -> mint).
- [x] 3.4 tests/_tiers.py FAST_MODULES registration (census-eligible).

## 4. Verification (real output in PR)

- [x] 4.1 BEFORE evidence: `uv run --project ~/.claude/skills/kunglao-agent
  python -c "import numpy"` fails (ModuleNotFoundError) on the stale
  install.
- [x] 4.2 Update the deployed framework install to a numpy-carrying
  commit; AFTER evidence: the same import + `import winrate_curve`
  (the #467 face chain) succeed.
- [x] 4.3 Gates: new suite green, ruff on touched files,
  devkit/quality_gates.py --quick, comment_hygiene_lint clean (paired
  re-mint), ext-scan --check (no new external refs expected).

## 5. Review + spec gates

- [ ] 5.1 openspec validate issue-467-deploy-numpy --strict.
- [ ] 5.2 Independent code-reviewer subagent on the staged diff; PASS ->
  .claude/reviews/467-*.md evidence + review_gate mint.
- [ ] 5.3 PR body: before/after evidence, gates output, Requirement ->
  implementation -> test mapping table.
- [ ] 5.4 CI five legs green; merge per dev-branch protection.
