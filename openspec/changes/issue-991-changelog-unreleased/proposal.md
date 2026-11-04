# issue-991-changelog-unreleased — fold the post-rc2 dev wave into CHANGELOG

## Why

`CHANGELOG.md` still ends at `## [0.1.6-rc2] - 2026-10-17`, matching the
released `origin/master` (`692059a6`, tag `v0.1.6-rc2`). The development
line `origin/dev` (`8aad57c1`, 2026-11-04) is 448 commits / 98 merged PRs
ahead — 680 files, +93,469 / −4,658 lines — and `CHANGELOG.md` has zero
diff against the release base. Anyone installing or deploying from dev
therefore sees a change record that stops at 10-17, and the next GitHub
Release notes cannot be drafted from the changelog. Tracked as issue #991.

## What Changes

- Add one `## [Unreleased]` section immediately above the rc2 section,
  following the file's existing Keep a Changelog 1.1 / PEP 440 format.
- Group the wave into `### Added` / `### Changed` / `### Fixed`, with a
  `(#NNN)` issue reference on every bullet and coverage of all six
  post-rc2 stages: governance/evidence base (11 PRs), learning-kernel and
  eval base (27), RL v2 kernel (20), RL v2 unified loop (26), RL v3 (7),
  remote-only increment / deps / docs (7).
- Record the #801 gate-layering reversal explicitly under `### Changed`:
  it SUPERSEDES the 2026-09-28 gate-error fail-closed ruling, keeps five
  HARD classes blocking, and demotes `format` / `self_health` to WARN +
  telemetry + rc 0. It is a security-posture change, not a bugfix.
- Extend `tests/test_changelog.py` with two contract tests (TDD): section
  shape / bullet attribution, and wave coverage / reversal wording.
- Leave `pyproject.toml` and `release-manifest.yaml` at `0.1.6-rc2`.

## Capabilities

### New Capabilities

- `changelog-unreleased`: the development line carries an attributable,
  mechanically checked record of every shipped wave since the last
  release tag.

### Modified Capabilities

- None. This change adds documentation and a documentation contract; no
  runtime behaviour, schema, or shipped asset changes.

## Impact

- Files: `CHANGELOG.md`, `tests/test_changelog.py`, and this OpenSpec
  change directory.
- No runtime code, no version sources, no tag, no GitHub Release, no
  dev → master merge.
- `tests/test_changelog.py` is already registered in `tests/_tiers.py`;
  extending it avoids new-module registration in the tier and test
  inventories.
- `formal_code_lint.py` scans only production comments/docstrings under
  `scripts/`, `tools/`, `hooks/`; neither changed file is in scope.
