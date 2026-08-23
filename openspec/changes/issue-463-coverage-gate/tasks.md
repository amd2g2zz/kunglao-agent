# Tasks — 4-Gate Quality Framework (issue #463, v0.1.2)

## Phase 1 (this PR): framework + observability + git hook

- [x] 1.1 Write `devkit/docs/quality_gates.md` (central policy doc)
- [x] 1.2 Re-write openspec/{proposal,design,spec}.md for 4-gate
- [x] 1.3 Move devkit scaffolding OUT of scripts/ and docs/
  - devkit/quality_gates.py (cross-platform Python, NOT bash — Windows compat)
  - devkit/pass_rate_metric.py (junit XML observation)
  - devkit/docs/{quality_gates,quality_roadmap,defect_escape_rate,unit_test_spec}.md
- [x] 1.4 Update `pytest.ini` — REMOVED `--cov-fail-under` (kept `--cov` for report)
- [x] 1.5 Update `pyproject.toml` — added `pytest-cov` + `mutmut` dev deps
- [x] 1.6 Update `.github/workflows/release-check.yml` — coverage upload only + 4-gate runner step
- [x] 1.7 Add `devkit/README.md` (layout convention: scripts vs devkit vs docs)
- [x] 1.8 Write `devkit/install_git_hooks.py` + `devkit/githooks/pre-commit` (anti-forgery stamped)
- [x] 1.9 Write `devkit/docs/unit_test_spec.md` (anti-patterns + when to stop)
- [x] 1.10 Write `tests/test_devkit_*.py` (21 tests: install hooks, pass rate, quality gates)
- [x] 1.11 Local sanity: `uv run python devkit/quality_gates.py` exit 0
- [ ] 1.12 Commit + push + open PR

## Phase 2 (follow-up PR): CI integration of Gate 4 + Gate 3

- [ ] 2.1 mutmut runs on PR diff (`--paths-to-mutate=$(git diff ...)`)
- [ ] 2.2 Regression suite runs in dedicated CI job (separate from unit)
- [ ] 2.3 Architecture complexity check (radon / xenon) — fail on >X
- [ ] 2.4 Bandit critical security check (zero tolerance)
- [ ] 2.5 KPI dashboard published per-PR

## Phase 3 (follow-up PR): KPI automation

- [ ] 3.1 First-Pass Acceptance Rate: track via PR merge events
- [ ] 3.2 Defect Escape Rate: auto-label at release time (labeler bot)
- [ ] 3.3 Rework Rate: review comment count + threshold
- [ ] 3.4 Quarterly retro doc update

## Anti-pattern reminders (do NOT do)

- ❌ Add `--cov-fail-under` to pytest.ini
- � Add tests purely to increase count
- ❌ Add tests purely to increase Coverage
- ❌ Set Test Case Count as a KPI
- ❌ Treat "all tests pass" as proof of requirement correctness
- ❌ Add regression test = "skipped" or "xfail" without justification
