## ADDED Requirements

### Requirement: The skill SHALL declare its request argument in the frontmatter

`SKILL.md` frontmatter SHALL declare the named positional argument `request` via the standard fields: `arguments: [request]` and `argument-hint: [request]`. The argument is the user REQUEST — a subcommand or a natural-language need. It SHALL NOT be `workspace`: the frontmatter `arguments` list SHALL NOT contain `workspace`.

#### Scenario: frontmatter declares the request argument

- **WHEN** the SKILL.md frontmatter is parsed as YAML
- **THEN** it contains an `arguments` list with `request` and an `argument-hint` whose value references `request`, and the `arguments` list does NOT contain `workspace`

### Requirement: The skill body SHALL consume the request as a subcommand or natural-language need

`SKILL.md` SHALL contain an `## Arguments` section stating the invocation form `/kunglao-agent [request]` and the two-form consumption rule:

1. **Subcommand** (exact, case-insensitive): `init` (Phase 0 workspace init), `analysis` (alias `analyze`; the default convergence loop), `verify [fact_id]` (M3 verify chain only), `resume` (alias `continue`; idempotent continuation), and mechanical CLI passthrough `decide` `tick` `record` `health` `monitor` `digest` `eval`.
2. **User request** (anything else): mapped by intent keywords to a subcommand (初始化/工作区→`init`; 分析/收敛/循环/deep analysis→`analysis`; 验证→`verify`; 健康/状态→`health`; unrecognized→`analysis`).

The section SHALL state that workspace is NEVER a parameter — workspace detection always runs in Phase 0 per the Local defaults table — and that empty `$ARGUMENTS` defaults to `analysis`.

#### Scenario: body consumes the request as subcommand or need

- **WHEN** the SKILL.md body is read
- **THEN** it contains the `## Arguments` section referencing `$ARGUMENTS`, listing the subcommand set (`init`, `analysis`, `verify`, `resume` present), stating the natural-language mapping rule (keyword → subcommand), stating the workspace-is-never-a-parameter rule, and stating the empty-`$ARGUMENTS` default (`analysis`)

### Requirement: The repository SHALL NOT contain a .claude-plugin directory, and deployment docs SHALL forbid it

The repo root SHALL NOT contain `.claude-plugin/` (plugin.json / marketplace.json): a skills-directory plugin identity breaks bare `/kunglao-agent` invocation in fresh sessions (regression 7f5f179, 2026-08-10 — a local-only misdiagnosed fix that never reached GitHub). `README.md` Installation SHALL state that plain-skill deployment (clone to `~/.claude/skills/kunglao-agent/`) is the standard and that adding `.claude-plugin/` is prohibited.

#### Scenario: no plugin-ification in the repo

- **WHEN** the repo root is inspected
- **THEN** no `.claude-plugin/` directory exists

#### Scenario: deployment docs forbid plugin-ification

- **WHEN** `README.md` Installation section is read
- **THEN** it documents the plain-skill clone deployment and explicitly warns against adding `.claude-plugin/`

### Requirement: The invocation contract SHALL be regression-guarded by tests

`tests/test_skill_invocation.py` SHALL cover: (a) frontmatter `arguments`/`argument-hint` declaring `request` and not `workspace`, (b) body `## Arguments` section with the subcommand set, natural-language mapping rule, and workspace-auto-detection statement, (c) absence of `.claude-plugin/` at the repo root. These tests SHALL be written RED before the GREEN implementation. The pre-existing failures `test_acceptance_overall_passes` and `test_contract_docs::test_skill_lte_500_lines` SHALL remain unchanged.

#### Scenario: contract tests fail RED before implementation

- **WHEN** `tests/test_skill_invocation.py` runs against the baseline (pre-change) tree
- **THEN** the frontmatter and body-contract tests fail (they assert the request semantics that the workspace-rule baseline violates), and all three pass after the change lands

#### Scenario: pre-existing failures are untouched

- **WHEN** the full `tests/` + `scripts/` suites run after the change
- **THEN** no new failures appear beyond `test_acceptance_overall_passes` and `test_contract_docs::test_skill_lte_500_lines`
