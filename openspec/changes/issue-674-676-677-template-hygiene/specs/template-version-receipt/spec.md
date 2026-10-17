# template-version-receipt delta — issue-674-676-677-template-hygiene

## ADDED Requirements

### Requirement: The deployed copy resolves the skill version from its deploy receipt

`template_version.read_skill_version()` SHALL resolve the version in the
order `pyproject.toml` → `.claude-plugin/plugin.json` →
`deployed-manifest.json` `source_version` → raise. The workspace-deployed
copy — whose root holds the manifest carrier and, by design, neither repo
version asset — SHALL return the receipt version instead of raising; the
skill tree SHALL keep resolving `pyproject.toml` first (byte-identical
in-tree behavior).

#### Scenario: a deployed root resolves through the carrier receipt

- **WHEN** `read_skill_version()` executes from a root that holds only a
  `deployed-manifest.json` declaring `source_version: 9.9.9`
- **THEN** it returns `9.9.9` and does not raise

#### Scenario: skill-tree precedence is unchanged

- **WHEN** the root declares `pyproject.toml` version `1.2.3` and also
  carries a manifest receipt of `9.9.9`
- **THEN** it returns `1.2.3`

#### Scenario: the release-defect guard still stands

- **WHEN** no source of version exists at the root (or the carrier is
  present but unreadable or versionless)
- **THEN** `read_skill_version()` raises `RuntimeError` naming all three
  sources

### Requirement: The deployed workspace gate returns a verdict, never a traceback

`convergence_check`'s version-consistency gate SHALL complete when
executed from the deployed copy: a workspace whose stamp equals the
resolved skill version passes the gate; a mismatch SHALL report the
upgrade path as a reason string/exit — a `RuntimeError` out of the gate
is a defect.

#### Scenario: deployed-copy gate completes on an aligned workspace

- **WHEN** `_require_workspace()` runs from the deployed form against a
  workspace whose `CLAUDE.md` stamp equals the receipt version
- **THEN** it returns the resolved workspace path with no exception

#### Scenario: deployed-copy gate reports a mismatch as a verdict

- **WHEN** the same gate runs against a workspace stamped with a
  different version
- **THEN** it exits with the version-mismatch path and its reason string,
  not with a version-resolution `RuntimeError`
