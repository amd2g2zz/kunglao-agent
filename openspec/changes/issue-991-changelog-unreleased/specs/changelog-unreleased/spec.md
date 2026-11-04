# issue-991-changelog-unreleased — delta spec

## ADDED Requirements

### Requirement: An Unreleased section records the post-rc2 development wave

`CHANGELOG.md` SHALL carry a `## [Unreleased]` section positioned above
`## [0.1.6-rc2] - 2026-10-17`. It SHALL contain `### Added`,
`### Changed` and `### Fixed` subsections, hold at least twelve bullets,
and every bullet SHALL carry a `(#NNN)` issue reference. The section
SHALL reference at least one issue from each of the six post-rc2 waves:
governance/evidence base, learning-kernel and eval base, RL v2 kernel,
RL v2 unified loop, RL v3, and the remote-only increment.

#### Scenario: a reader opens the changelog on the development line

- **WHEN** `CHANGELOG.md` is read from the development branch
- **THEN** the first version-level section is `[Unreleased]`, the rc2
  section follows it unchanged, and all three subsections are present

#### Scenario: every entry is attributable to the tracker

- **WHEN** the Unreleased section is parsed into bullet lines
- **THEN** each bullet contains a `(#NNN)` reference, the section holds
  at least twelve bullets, and each of the six waves is represented

### Requirement: The gate-layering reversal is recorded explicitly

The Unreleased section SHALL state that issue #801 SUPERSEDES the
2026-09-28 gate-error fail-closed ruling. It SHALL name the five HARD
classes `corruption`, `reward_integrity`, `termination_budget`,
`evidence` and `execution_surface`, and SHALL describe the demotion of
`format` and `self_health` to WARN plus telemetry plus rc 0 as a
deliberate security-posture change under `### Changed`, never as a
bugfix under `### Fixed`.

#### Scenario: the reversal survives a keyword audit

- **WHEN** the Unreleased section is searched for `SUPERSEDES`,
  `fail-closed`, and the five HARD class names
- **THEN** every term is present and the reversal is filed under
  `### Changed`

#### Scenario: observability is not misstated as blocking

- **WHEN** the reversal entry describes the demoted classes
- **THEN** it states that the tool call proceeds with rc 0 and names the
  sidecar, ledger row and warn breaker as compensating observability

### Requirement: Released version identity is untouched

`pyproject.toml` and `release-manifest.yaml` SHALL remain at
`0.1.6-rc2`. This change SHALL NOT bump a version, create a tag, publish
release notes, merge dev into master, or resolve the #801 call-site
attribution question.

#### Scenario: the release contract still passes

- **WHEN** `tests/test_changelog.py` and
  `scripts/release_receipt.py --check` run after the change
- **THEN** the version pin remains green and the receipt check returns
  rc 0

#### Scenario: only the intended files change

- **WHEN** the staged diff is inspected
- **THEN** it contains `CHANGELOG.md`, `tests/test_changelog.py` and this
  OpenSpec change directory, and no runtime or version-source file
