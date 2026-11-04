# issue-991-changelog-unreleased — tasks

1. [x] SDD: OpenSpec change directory (proposal / design / tasks / delta
   spec), `openspec validate` clean.
2. [x] RED: extend `tests/test_changelog.py` with
   `test_unreleased_section_shape` and
   `test_unreleased_section_covers_all_waves_and_the_gate_reversal`;
   confirm both fail with `missing [Unreleased] section`.
3. [x] GREEN: add the `## [Unreleased]` section to `CHANGELOG.md` above
   `## [0.1.6-rc2] - 2026-10-17`, covering all six post-rc2 waves across
   `### Added` / `### Changed` / `### Fixed` with 19 attributed bullets.
4. [x] Record the #801 reversal under `### Changed` with the literal
   `SUPERSEDES` / `fail-closed` wording and all five HARD class names.
5. [x] Verify version identity is untouched: `pyproject.toml` and
   `release-manifest.yaml` remain `0.1.6-rc2`.
6. [x] Targeted TDD contract: `python -m pytest -q tests/test_changelog.py`
   → 5 passed (RED was 2 failed / 3 passed).
7. [x] `openspec validate issue-991-changelog-unreleased --strict` exits 0
   (`Change ... is valid`). The `npx` wrapper hangs in this non-interactive
   environment; invoke the cached CLI entry `bin/openspec.js` directly.
8. [x] `python scripts/release_receipt.py --check` rc 0.
9. [ ] Full `python -m pytest -q` on one process is not viable locally:
   23 minutes reached only 4% (CI splits it into four parallel legs with
   xdist). Deferred to the PR's CI legs; targeted contract is green.
10. [ ] 1 independent subagent reviewer PASS on the exact staged diff,
    gate token minted, commit, PR to `dev` referencing issue #991.
