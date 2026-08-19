# Spec — 4-Gate Quality Framework (issue #463, v0.1.2)

## G1: Requirement Correctness

### Requirement: every PR MUST cite an issue + acceptance criteria

A PR without a referenced issue MUST be rejected at PR-creation time
(GitHub PR template enforces).

### Requirement: acceptance tests MUST exist for the cited issue

If the issue's acceptance criteria are testable, there MUST be tests
that exercise them. Pure-doc changes are exempt.

### Requirement: agent-self-generated expected results MUST NOT be the sole oracle

A test that uses values the agent invented during implementation is NOT
a valid acceptance test for Gate 1. Acceptance tests MUST come from:
- The issue's acceptance criteria
- A spec / contract / schema definition
- An external reference (documented CVE, RFC, etc.)

## G2: Regression Safety

### Requirement: pytest MUST pass 100% before merge

The standard test command (`pytest -q`) MUST exit 0. No skipped,
no failures. Baseline failures are tracked separately (see G2.b).

### Requirement: G2.b — historical bugs MUST continue to regress

Each historical bug (issue with label `regression-test` or `bug`) MUST
have at least one test that exercises the bug path. Adding a fix
without adding the regression test is a Gate 2 fail.

### Requirement: integration / E2E tests cover the public CLI surface

The 9 CLIs (per `release-manifest.yaml` `clis:` list) MUST each have
a `--help` exit-0 test. New CLI MUST add its test in the same PR.

## G3: Engineering Quality

### Requirement: `uv run python -m pytest --collect-only` MUST succeed

Import errors are Gate 3 fails.

### Requirement: `uv run python -c "import kunglao_init"` MUST succeed

Smoke import for the public entry.

### Requirement: lint MUST pass (`ruff` or current lint tool)

Critical security issues (`bandit` `B`/`HIGH`) = 0.

### Requirement: Change Size MUST be reasonable

A single PR >1500 lines diff (excluding fixture data) triggers
**mandatory additional review** (not auto-reject — risk identifier).

### Requirement: Architecture Violation MUST be 0

A change that breaks the layering (e.g. `hooks/` calling `tools/_lib/`
directly without going through `scripts/`) is Gate 3 fail.

## G4: Test Effectiveness

### Requirement: `mutmut run` on changed code MUST be available locally

`mutmut run --paths-to-mutate=<changed.py>` MUST work. Phase 1 only
sets up config; Phase 2 enforces threshold.

### Requirement: critical paths MUST have invariant tests

State-machine / decision / lifecycle code MUST have property or
invariant tests, not just example tests. Phase 2+.

### Requirement: boundary / error cases MUST be tested

Negative paths (invalid input, missing file, etc.) MUST be tested.

## Cross-cutting

### Requirement: Coverage is observation only

`pytest.ini` MAY have `--cov` for report. MUST NOT have `--cov-fail-under`.

### Requirement: Test Case Count is observation only

`tests/` file count is not enforced. Adding tests for the sake of count
is anti-pattern; per the user directive and `devkit/docs/unit_test_spec.md`.

### Requirement: KPI tracking infrastructure MUST exist

`devkit/docs/quality_roadmap.md` MUST track:
- First-Pass Acceptance Rate (per release)
- Defect Escape Rate (per release)
- Regression Rate (per release)
- Rework Rate (per release)

`devkit/docs/defect_escape_rate.md` is one slice; roadmap is the master view.

### Requirement: dev scaffolding MUST live under devkit/

All developer-facing tooling (quality gates, metric extractors, fault
injection fixtures, mutmut runners, git hook deployer) MUST live under
`devkit/`. NOT mixed into `scripts/` (which is the shipped product surface).

### Requirement: development docs MUST live under devkit/docs/

Policy / KPI / roadmap / unit-test-spec documents for developers MUST
live under `devkit/docs/`. NOT mixed into `docs/` (which is user-facing).

### Requirement: PR review output MUST follow 4-gate order

When reviewing a PR, output (in order):
1. 4 gates Pass/Fail + evidence
2. Real risks found
3. Test inflation check
4. Rework needed?
5. Delivery quality impact

Per `devkit/docs/quality_gates.md`.

### Requirement: quality_gates runner MUST be cross-platform

`devkit/quality_gates.py` is pure Python (no bash-only constructs).
No `set -e`, no shell `printf`, no `subprocess` with shell=True default.
Windows / Linux / macOS must produce identical results.

### Requirement: install_git_hooks MUST stamp absolute devkit path

`devkit/install_git_hooks.py` MUST replace `__KUNGLAO_DEVKIT_ROOT__`
placeholder in the deployed `.git/hooks/pre-commit` with the absolute
devkit root path (anti-forgery: commit-time env cannot alter the literal).

### Requirement: install_git_hooks MUST back up pre-existing hooks

If `.git/hooks/<name>` already exists, the installer MUST write a backup
to `.git/hooks/<name>.bak-<UTC-ts>` before overwriting.

### Requirement: install_git_hooks MUST refuse to remove foreign hooks

`--uninstall` MUST only remove hooks carrying the `# devkit-installed:`
marker. Foreign hooks (e.g. product's review gate) MUST be reported and
left untouched.

### Requirement: unit_test_spec.md MUST exist

`devkit/docs/unit_test_spec.md` MUST document:
- Anti-patterns (coverage padding, tautology tests, behaviour-less names)
- When to STOP adding tests (KPI signal table)
- Naming conventions
- AAA structure
- Property/invariant test requirement for state-machine code

Per the user directive "测试是手段,不是指标".
