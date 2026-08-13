# Design — skill loader + arguments (#90)

## Context

User: "kunglao-agent 依然不被skill loader所加载，skill不支持参数" (2026-08-12).

Official loader mechanics (confirmed via code.claude.com/docs/en/skills.md + plugins-reference.md):
- Skill discovery is directory-based (`~/.claude/skills/<name>/SKILL.md`); no settings.json registration needed; command name = directory name for personal/project skills.
- A directory containing `.claude-plugin/plugin.json` is loaded in the NEXT session as a skills-directory plugin (`<name>@skills-dir`), NOT a plain skill — the two identities are mutually exclusive. Bare-name invocation of a plugin skill exists only as a v2.1.216+ fallback.
- Arguments: `/skill-name <args>`; the body consumes them via placeholders `$ARGUMENTS` (all), `$ARGUMENTS[N]` / `$N` (positional), `$name` (named, mapped positionally from frontmatter `arguments:` list). If the body has no `$ARGUMENTS`, args are only appended as a trailing `ARGUMENTS: <value>` line — easily ignored.
- Standard frontmatter fields include `arguments:` (named args) and `argument-hint:` (completion hint). `triggers` is non-standard but ignored, not rejected.

Local install facts: `~/.claude/skills/kunglao-agent/.claude-plugin/` exists (commit `7f5f179`, local-only, never in GitHub repo); SKILL.md frontmatter YAML valid no BOM; body has zero `$ARGUMENTS` consumption; Claude Code 2.1.228.

Constraints: this is a contract/invocation-surface fix, not a dispatch-model change. The GitHub repo is the source of truth; the local `~/.claude/skills/kunglao-agent/` is a deployment clone (README L119).

## Goals / Non-Goals

**Goals:**
- kunglao-agent loads as a plain skill in any fresh session: `/kunglao-agent` resolves.
- `/kunglao-agent <workspace>` passes the workspace argument into the contract, which consumes it in Phase 0 workspace detection; empty args fall back to the documented default.
- Deployment docs forbid re-adding `.claude-plugin/` (the 7f5f179 mistake).
- Regression tests guard all three.

**Non-Goals:**
- No plugin-marketplace path, no `kunglao-agent@skills-dir` identity, no plugin.json authoring.
- No changes to the dispatch loop, hooks, scripts, agents, references, or DESIGN.md.
- No `triggers`-to-`when_to_use` rename in this change (non-standard field is harmless; renaming touches the description budget — defer unless the user asks).
- No changes to other skills (research-tree's own `.claude-plugin/` is out of scope).

## Decisions

### D1. Frontmatter: declare the named argument

Add to SKILL.md frontmatter:

```yaml
arguments: [workspace]
argument-hint: [workspace]
```

Rationale: `arguments:` is the standard named-argument declaration (positional mapping), `argument-hint:` drives the autocomplete hint shown for `/kunglao-agent <…>`. Both are standard fields per official docs; no custom schema.

### D2. Body: "## Arguments" consumption protocol

Insert a short section above the "Local defaults" table (the section that currently owns workspace detection):

```markdown
## Arguments

Invocation: `/kunglao-agent [workspace]`

- `$ARGUMENTS` non-empty: the first argument is the workspace path (e.g.
  `<WORKSPACE_ROOT>/samples/<YYYY-MM-DD>/malware-analysis-workspace`). Phase 0
  workspace detection uses this path directly — do not guess from the
  workspace pattern.
- `$ARGUMENTS` empty: detect per the Local defaults table below.
```

Consumption: `$ARGUMENTS` (generic) with the first-token rule; `$workspace` (named per frontmatter) is equivalent. The section sits next to Phase 0 / Local defaults so a fresh reader connects the parameter to setup. This is a text contract — no script changes needed (YAGNI: the workspace path is consumed by the orchestrator's own file reads, which already take a workspace argument everywhere).

### D3. Deployment docs: forbid plugin-ification

README "Installation" section, after the clone command: add a note —

> Deploy as a plain skill (clone to `~/.claude/skills/kunglao-agent/`). Do NOT add a `.claude-plugin/` directory: that converts the skill into a `skills-directory` plugin in the next session and breaks bare `/kunglao-agent` invocation (regression 7f5f179, 2026-08-10).

### D4. RED-first regression tests: `tests/test_skill_invocation.py`

- `test_skill_frontmatter_declares_arguments`: SKILL.md frontmatter contains `arguments:` and `argument-hint:` keys (parse frontmatter with yaml).
- `test_skill_body_consumes_arguments`: SKILL.md body contains the `## Arguments` section and the `$ARGUMENTS` placeholder with the workspace rule.
- `test_repo_has_no_claude_plugin_dir`: repo root has no `.claude-plugin/` directory (guards against repeating 7f5f179).
- Baseline: pre-existing failures (`test_acceptance_overall_passes`, `test_contract_docs::test_skill_lte_500_lines`) unchanged.

## Risks / Trade-offs

- **Description budget overflow** (200+ skills in this environment; 1% listing budget): most-recently-used descriptions get dropped first, affecting auto-trigger only — manual `/kunglao-agent` invocation is unaffected. Not addressed here; noting for future.
- **`triggers` non-standard field**: ignored by the loader, no rejection. Left as-is (rename deferred — see Non-Goals).
- **Text-contract-only parameter support**: no script parses the workspace arg. Sufficient because every downstream consumer (scripts/, hooks/) already takes the workspace as a positional argument; the skill contract just tells the model where to get it.
- **Local identity switch needs a fresh session**: after removing `.claude-plugin/`, the change takes effect in the next session (loader watches existing directories live; identity changes need session restart). Documented in the PR body.

## Migration Plan

1. SDD commit: this change's proposal/design/spec/tasks.
2. RED: `tests/test_skill_invocation.py` written first, fails.
3. GREEN: frontmatter fields (D1), Arguments section (D2), README note (D3).
4. Verify: full `tests/` + `scripts/` suites — no new failures beyond the pre-existing two; `openspec validate` RC=0.
5. PR + orchestrator verification (maker-checker); no merge by the maker.
6. Post-merge deployment (outside PR): remove `~/.claude/skills/kunglao-agent/.claude-plugin/`, `git pull` on the deployment clone; verify in a fresh session.

## Open Questions

None blocking. Local cleanup timing (step 6) is a deployment action independent of the merge.
