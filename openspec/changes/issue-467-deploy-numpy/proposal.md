# issue-467-deploy-numpy — manifest-vs-imports consistency gate: the deployed env must cover the deployed code's hard imports

## Why

Live evidence (E2E round-6, e2e-ws-20260930-060104): 218 warn rows in one
run — 107x `heartbeat_touch.activity_sidecar` ModuleNotFoundError, 107x
`statusline_snapshot winrate_face` ModuleNotFoundError, 4x
`hook_activation renew_2` "No module named 'numpy'".

Root cause chain (verified):

1. Hooks run as `PYTHONUTF8=1 uv run --project <FRAMEWORK_ROOT> python
   <workspace-script>` (hook_activation.build_hook_entry, #445 single
   source; 0.1.6 sweep #6: the ENV is the framework install root —
   `~/.claude/skills/kunglao-agent` — whose pyproject.toml + uv.lock own
   the dependency set).
2. The CODE is the workspace deployed copy (`<ws>/.claude/scripts/`,
   materialized from the EXECUTING tree by hook_activation.
   deploy_workspace_copy / deployed_refresh per deploy-manifest.yaml).
3. #422 added `numpy>=2.2` to the repo pyproject (RLVR statistical math);
   #420/#465 consolidated the RLVR faces onto `scripts/rlvr/*`, whose
   module-level `import numpy` is UNGUARDED (hard dependency).
4. The production framework install was a stale clone (v0.1.5.post1; even
   v0.1.5.post2 master predates numpy — numpy is 0.1.6-dev only): its
   pyproject.toml AND uv.lock carry no numpy.
5. Init from the 0.1.6 repo deployed fresh code into the workspace while
   the hook commands kept resolving the env to the stale install →
   every numpy-backed face died per tick and failed open.

The existing truth machinery checks files and wiring, never dependency
coverage: #783/#810 deploy-manifest tracks per-file sha256 (a numpy-less
manifest is byte-consistent); #412 hooks_selfcheck verifies component
ACTIVATION (wiring, MCP, oracle) not importability; the release-receipt
test only substring-asserts five hardcoded dep names. Nothing refuses a
deployment whose env project cannot serve the code's imports.

## What Changes

1. **Gate module** `scripts/dep_surface_gate.py` (new, pure): AST-scan a
   package tree's deployed Python surface (hooks/, scripts/ incl.
   scripts/rlvr/, tools/) for HARD third-party imports — unguarded
   module/function-level imports; imports inside `try/except
   ImportError|ModuleNotFoundError|Exception` are GUARDED (degrade-by-
   design, exempt); stdlib (`sys.stdlib_module_names`) and in-tree
   modules are exempt; import-name→distribution normalization (PEP 503 +
   alias table: `yaml`→`PyYAML`, `z3`→`z3-solver`). `check(surface_root,
   env_root=None)` reports `{ok, missing: [{module, dist, needed_by}],
   guarded_undeclared}`; CLI exits 1 on missing.
2. **CI leg** (release-check.yml lint-hygiene): repo self-check — the
   repo's hard import surface must be covered by the repo pyproject
   `[project].dependencies`. Catches the code-lands-before-manifest
   class at PR time.
3. **Deploy-time refusal**: `deploy_workspace_copy` runs
   `check(surface=<executing tree>, env=_framework_project_root())`
   BEFORE copying and raises RuntimeError on missing deps (init exits
   non-zero) — the #467 mixed-drift shape (fresh code + stale env root)
   can no longer produce a silently-broken workspace. The refusal names
   the modules, the env root, and the remediation (update the skill
   package).
4. **Upgrade posture**: `deployed_refresh.refresh` runs the same gate
   and surfaces a gap as a WARN detail (its never-raise migration
   contract stands); the kunglao_log warn face makes it day-log
   observable.
5. **Deployed package update** (operational, evidence in PR): the
   production framework install is updated to a numpy-carrying commit;
   end-to-end proof `uv run --project ~/.claude/skills/kunglao-agent
   python -c "import numpy, winrate_curve"` passes before/after shown.

## Non-goals

- No per-tick selfcheck component row: the full AST scan costs ~5 s —
  acceptable one-shot at init/CI, wrong on the heartbeat tick path
  (YAGNI; the deploy refusal is the load-bearing gate).
- No pyproject/uv.lock copying into workspaces: workspaces ship no
  project by design (#6 sweep); the env stays framework-root-owned.
- No dynamic `__import__`/string-form import resolution in v1 (none
  exist on the third-party surface today; if one appears, the #810
  dynamic-ref regex precedent extends the scanner).
- No change to v0.1.5.x install backcompat: a stale install deploying
  its own consistent tree still passes; only the mixed-drift shape
  refuses.
