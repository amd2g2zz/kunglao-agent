## ADDED Requirements

### Requirement: The skill SHALL declare its workspace argument in the frontmatter

`SKILL.md` frontmatter SHALL declare the named positional argument `workspace` via the standard fields: `arguments: [workspace]` and `argument-hint: [workspace]`. This makes the parameter explicit to the loader (autocomplete hint) and to the invoking model (named argument mapping).

#### Scenario: frontmatter declares the argument

- **WHEN** the SKILL.md frontmatter is parsed as YAML
- **THEN** it contains an `arguments` list with `workspace` and an `argument-hint` whose value references `workspace`

### Requirement: The skill body SHALL consume the workspace argument

`SKILL.md` SHALL contain an `## Arguments` section stating the invocation form `/kunglao-agent [workspace]` and the consumption rule: when `$ARGUMENTS` is non-empty, the first argument is the workspace path (e.g. `<WORKSPACE_ROOT>/samples/<YYYY-MM-DD>/malware-analysis-workspace`) and Phase 0 workspace detection SHALL use it directly instead of guessing from the workspace pattern; when `$ARGUMENTS` is empty, detection SHALL fall back to the Local defaults table.

#### Scenario: body consumes the argument

- **WHEN** the SKILL.md body is read
- **THEN** it contains the `## Arguments` section with the `$ARGUMENTS` placeholder and both rules (non-empty → first arg = workspace path; empty → default detection)

### Requirement: The repository SHALL NOT contain a .claude-plugin directory, and deployment docs SHALL forbid it

The repo root SHALL NOT contain `.claude-plugin/` (plugin.json / marketplace.json): a skills-directory plugin identity breaks bare `/kunglao-agent` invocation in fresh sessions (regression 7f5f179, 2026-08-10 — a local-only misdiagnosed fix that never reached GitHub). `README.md` Installation SHALL state that plain-skill deployment (clone to `~/.claude/skills/kunglao-agent/`) is the standard and that adding `.claude-plugin/` is prohibited.

#### Scenario: no plugin-ification in the repo

- **WHEN** the repo root is inspected
- **THEN** no `.claude-plugin/` directory exists

#### Scenario: deployment docs forbid plugin-ification

- **WHEN** `README.md` Installation section is read
- **THEN** it documents the plain-skill clone deployment and explicitly warns against adding `.claude-plugin/`

### Requirement: The invocation contract SHALL be regression-guarded by tests

`tests/test_skill_invocation.py` SHALL cover: (a) frontmatter `arguments`/`argument-hint` declaration, (b) body `## Arguments` section with `$ARGUMENTS` consumption, (c) absence of `.claude-plugin/` at the repo root. These tests SHALL be written RED before the GREEN implementation. The pre-existing failures `test_acceptance_overall_passes` and `test_contract_docs::test_skill_lte_500_lines` SHALL remain unchanged.

#### Scenario: contract tests fail RED before implementation

- **WHEN** `tests/test_skill_invocation.py` runs against the baseline (pre-change) tree
- **THEN** the frontmatter and body-consumption tests fail, and all three pass after the change lands

#### Scenario: pre-existing failures are untouched

- **WHEN** the full `tests/` + `scripts/` suites run after the change
- **THEN** no new failures appear beyond `test_acceptance_overall_passes` and `test_contract_docs::test_skill_lte_500_lines`
