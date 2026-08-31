# Design — 4-Gate Quality Framework (issue #463, v0.1.2)

## Architecture

The 4 gates are NOT a single tool — they're a **process** that runs at PR
review time. Each gate has both **automated** and **manual** checks:

```
                              ┌─────────────────────────┐
                              │   PR Review Workflow    │
                              └────────────┬────────────┘
                                           │
              ┌────────────────────────────┼────────────────────────────┐
              │                            │                            │
              ▼                            ▼                            ▼
      ┌──────────────┐             ┌──────────────┐             ┌──────────────┐
      │ Automated    │             │ Automated    │             │ Reviewer     │
      │ (CI)         │             │ (CI)         │             │ (human)      │
      └──────┬───────┘             └──────┬───────┘             └──────┬───────┘
             │                            │                            │
   ┌─────────┼─────────┐         ┌────────┼────────┐          ┌────────┼────────┐
   ▼         ▼         ▼         ▼        ▼        ▼          ▼        ▼        ▼
 Gate 1    Gate 2    Gate 3    Gate 4  ...       ...        ...      ...      ...
```

### Gate 1 (Requirement Correctness) — partial auto

- Automated: schema validation, contract tests, business invariant tests
- Manual: reviewer checks against the issue / acceptance criteria

### Gate 2 (Regression Safety) — mostly auto

- Automated: pytest, integration tests, E2E tests, historical bug regression suite
- Manual: review of new test interactions with old tests

### Gate 3 (Engineering Quality) — mostly auto

- Automated: `uv run python -m pytest` (imports + type), `ruff`/`flake8`,
  `radon`/`xenon` (complexity), `bandit` (security), diff size check
- Manual: architecture review, design choice sanity check

### Gate 4 (Test Effectiveness) — auto for changed code

- Automated: `mutmut run --paths-to-mutate=<changed_files>` on PR diff
- Manual: review of test design (does it cover boundary / property?)

## Files touched in this PR

- `devkit/docs/quality_gates.md` — central policy doc (replaces docs/quality_gates.md)
- `devkit/docs/quality_roadmap.md` — KPI tracking + observations (was docs/coverage_roadmap.md)
- `devkit/docs/defect_escape_rate.md` — defect escape metric tracking
- `devkit/quality_gates.py` — cross-platform 4-gate runner (Python, NOT bash — Windows compat)
- `devkit/pass_rate_metric.py` — junit XML metric extractor (observation only)
- `pytest.ini` — **remove** `--cov-fail-under` (keep `--cov` for report)
- `.github/workflows/release-check.yml` — coverage report upload (no fail)
- `pyproject.toml` — keep `pytest-cov` (for report) + `mutmut` (for Gate 4)
- `openspec/changes/issue-463-coverage-gate/` — fully rewritten for 4-gate framework
- `tests/test_log_setup.py` — kept (independent infra test, NOT counted as "凑 Coverage")

## Layout convention (user directive: don't mix scaffolding with source)

```
kunglao-agent/
├── scripts/      ← 产品源码(CLI、toolchain、init、...) only
├── tests/        ← 产品代码的测试 + devkit 自己的测试(test_devkit_*.py)
├── devkit/       ← 完整 dev 包:可执行 + 文档 + hooks
│   ├── *.py     (quality_gates / pass_rate_metric / install_git_hooks)
│   ├── githooks/ (hook 模板,带 __KUNGLAO_DEVKIT_ROOT__ 占位符)
│   ├── docs/    ← devkit 内部文档(policy / KPI / 单元测试规范)
│   └── tests/   (Phase 2:devkit 自己的测试 — 暂用 tests/test_devkit_*.py)
└── docs/         ← 产品文档(用户面向)
```

Why `devkit/` is a complete package:
- `devkit/*.py` is **executable** scaffolding (run by devs + CI)
- `devkit/docs/` is **read-only** policy / KPI tracking
- `devkit/install_git_hooks.py` deploys `githooks/*` to `.git/hooks/`
- `devkit/docs/unit_test_spec.md` is the canonical test-writing rulebook
  (anti-patterns + when to stop adding tests)
- `scripts/` stays pure product surface — must NOT contain dev-time tooling
- `docs/` stays user-facing (README, tutorial, changelog)

## git hook installer design

`devkit/install_git_hooks.py`:
- Idempotent:re-install overwrites with same stamp; safe to re-run.
- Anti-forgery:stamps absolute `__KUNGLAO_DEVKIT_ROOT__` path into deployed
  hook. Commit-time env cannot alter the literal (same pattern as #367).
- Pre-existing hooks backed up to `.git/hooks/<name>.bak-<UTC-ts>`.
- Refuses to uninstall non-devkit hooks(recognised by `# devkit-installed:` marker).
- Cross-platform pure Python;Windows / Linux / macOS identical.

Hook body (`devkit/githooks/pre-commit`):
- Runs Gate 1 + 3 + 4 (<10s on warm cache)
- Gate 2 (full pytest) opt-in via `$KUNGLAO_DEV_GATE2=1`
- Replaces the product's `.claude/git-hooks/pre-commit` (different concept:
  review gate vs quality gate)

## What this PR explicitly does NOT do

- ❌ Set a Coverage% threshold (anti-pattern per user)
- ❌ Set a Test Case Count threshold (anti-pattern)
- ❌ Write tests for the sake of tests
- ❌ Add `pytest-cov` as a fail gate

## What it DOES do

- ✅ Document the 4-gate framework as the canonical quality policy
- ✅ Provide observability (Coverage / Pass Rate reports, NOT thresholds)
- ✅ Add mutmut config so Gate 4 can run on demand
- ✅ Set up KPI tracking infrastructure (Defect Escape / First-Pass / Rework)
- ✅ Add a `scripts/run_quality_gates.sh` (or similar) helper to run all 4 gates locally

## Phase plan

### Phase 1 (this PR): framework + observability
- Documents + mutmut config + coverage report (no thresholds)
- ~300 lines (mostly docs + 1 small shell helper)

### Phase 2 (follow-up PR): CI integration
- mutmut runs on PR diff (Gate 4)
- Regression suite runs in dedicated job (Gate 2)
- Architecture complexity check fails on >X (Gate 3)
- Coverage report stays as observation

### Phase 3 (follow-up PR): KPI automation
- First-Pass Acceptance Rate: PR merge count without changes / total PR
- Defect Escape Rate: auto-label at release time
- Rework Rate: review comment count automation

## Risk

- mutmut baseline unknown (need Phase 1 dry-run to set P2 threshold)
- Gate 3 complexity threshold is subjective; needs calibration over time
- KPI history needs several release cycles to be meaningful

## Open

- mutmut whitelist/blacklist for dynamic imports / type hints?
- Where does `run_quality_gates.sh` live? `scripts/` or `tools/`?
- Should we publish per-PR KPI dashboard?
