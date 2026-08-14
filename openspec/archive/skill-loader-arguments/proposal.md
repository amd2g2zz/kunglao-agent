# Proposal — skill loader + arguments: plain-skill invocation with workspace parameter (#90)

## Why

User feedback (2026-08-12, verbatim): "kunglao-agent 依然不被skill loader所加载，skill不支持参数". Two root causes, both confirmed against official docs (code.claude.com/docs/en/skills.md, plugins-reference.md) and the local install:

1. **Local plugin-ification breaks plain-skill loading.** `~/.claude/skills/kunglao-agent/.claude-plugin/` (plugin.json + marketplace.json) was added locally by commit `7f5f179` (2026-08-10, "enable loader registration" — a misdiagnosed fix attempt that never reached GitHub). A skill directory containing `.claude-plugin/plugin.json` becomes a `skills-directory` plugin (`kunglao-agent@skills-dir`) in the NEXT session instead of a plain skill — bare `/kunglao-agent` only resolves via the v2.1.216+ fallback, and identity switching needs a fresh session. Result: the user still sees "not loaded". The GitHub repo has no `.claude-plugin/` — plugin-ification exists only in the local deployment clone.

2. **SKILL.md never consumes arguments.** Body has 0 hits for `$ARGUMENTS` / `$0` / `arguments` / `argument-hint`. Even when the loader passes args, they are only appended as a trailing `ARGUMENTS: <value>` line that the contract text never tells the model to consume → "skill 不支持参数".

Excluded root causes: `skillOverrides` absent; frontmatter YAML valid, no BOM; `triggers` is non-standard but ignored (not rejected); Claude Code 2.1.228 ≥ 2.1.216.

## What Changes

- **`SKILL.md` frontmatter**: add standard fields `arguments: [workspace]` and `argument-hint: [workspace]` (named positional argument; the hint drives autocomplete).
- **`SKILL.md` body**: new "## Arguments" consumption protocol near the Local defaults table — `/kunglao-agent <workspace>`: first argument = workspace path, Phase 0 workspace detection uses it instead of guessing from the workspace pattern; empty args → default detection. Consume `$ARGUMENTS` (positional fallback) / `$workspace` (named).
- **Deployment docs (`README.md` Installation)**: state that plain-skill deployment is the standard (clone to `~/.claude/skills/kunglao-agent/`); do NOT add `.claude-plugin/` — plugin-ification breaks bare `/kunglao-agent` invocation.
- **Regression tests (`tests/`)**: RED-first — (a) SKILL.md frontmatter contains `arguments:` and `argument-hint:`; (b) SKILL.md body contains the Arguments consumption protocol (`$ARGUMENTS`); (c) repo root has no `.claude-plugin/` (guards against repeating 7f5f179).
- **Local deployment cleanup (outside this PR)**: remove `~/.claude/skills/kunglao-agent/.claude-plugin/` (revert 7f5f179), `git pull` to sync dev.

## Capabilities

### New Capabilities

- `skill-loader-arguments`: the kunglao-agent skill loads as a plain skill with a workspace argument — `/kunglao-agent <workspace>` passes the workspace path into the skill contract, which consumes it in Phase 0 setup.

### Modified Capabilities

(none — first spec for the skill's invocation surface)

## Impact

- `SKILL.md` (frontmatter + Arguments section), `README.md` (Installation note), new `tests/test_skill_invocation.py`.
- Not touched: `DESIGN.md` (architecture history), `references/*`, `hooks/*`, `scripts/*`, `agents/*`, `memory/`, `rules/`, `templates/`, `eval/`.
- Pre-existing test failures (`test_acceptance_overall_passes`, `test_contract_docs::test_skill_lte_500_lines`) unchanged.
