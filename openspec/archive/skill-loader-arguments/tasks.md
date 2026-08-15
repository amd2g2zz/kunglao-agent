# Tasks — skill loader + arguments (#90)

## 1. Setup

- [x] 1.1 Worktree wt90 on branch `feat/skill-loader-arguments` at dev baseline `d89df4c` (one issue / one branch / one worktree)
- [x] 1.2 Read issue #90 in full: user feedback + root-cause diagnosis (local `.claude-plugin/` plugin-ification breaks plain-skill load; SKILL.md body never consumes `$ARGUMENTS`); official loader mechanics confirmed
- [x] 1.3 Grep ground truth: SKILL.md frontmatter (current keys), SKILL.md body for `$ARGUMENTS`/`arguments`/`argument-hint` (expect 0 hits), README Installation section, tests/ naming conventions

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 proposal.md (why: plugin-ification 7f5f179 misdiagnosed fix + no-args-consumption; what: frontmatter arguments/argument-hint, body Arguments section, README note, regression tests, local cleanup)
- [x] 2.2 design.md (D1 frontmatter named argument; D2 Arguments consumption protocol above Local defaults; D3 README forbid .claude-plugin; D4 RED-first tests; risks; migration)
- [x] 2.3 specs/skill-loader-arguments/spec.md (ADDED requirements: frontmatter arguments declaration / body consumption / no .claude-plugin + README forbid / regression tests)
- [x] 2.4 tasks.md
- [x] 2.5 `openspec validate` PASS (RC=0; use `npx.cmd --yes openspec` — the `new change` scaffold is broken in this environment, manual layout only)
- [x] 2.6 Commit openspec artifacts FIRST: `sdd(skill-loader-arguments): proposal/design/spec/tasks for issue #90`

## 3. RED tests (write first, must fail) — tests/test_skill_invocation.py

- [x] 3.1 `test_skill_frontmatter_declares_arguments`: parse SKILL.md frontmatter (yaml) → contains `arguments` key with `workspace` entry AND `argument-hint` key
- [x] 3.2 `test_skill_body_consumes_arguments`: SKILL.md body contains `## Arguments` section and `$ARGUMENTS` placeholder with the workspace rule (first arg = workspace path; empty → default detection)
- [x] 3.3 `test_repo_has_no_claude_plugin_dir`: repo root has no `.claude-plugin/` directory
- [x] 3.4 Confirm RED: `python -m pytest tests/test_skill_invocation.py -q` fails on the new tests (frontmatter/body assertions fail on current SKILL.md; plugin-dir assertion passes trivially — note this in the report: it guards the future, the RED evidence is 3.1/3.2)

## 4. GREEN implementation

- [x] 4.1 SKILL.md frontmatter: add `arguments: [workspace]` + `argument-hint: [workspace]` (D1)
- [x] 4.2 SKILL.md body: add `## Arguments` section above the Local defaults table — `/kunglao-agent [workspace]`; `$ARGUMENTS` non-empty → first arg = workspace path, Phase 0 uses it directly; empty → Local defaults detection (D2)
- [x] 4.3 README Installation: after the clone command, add the plain-skill deployment note — do NOT add `.claude-plugin/` (plugin-ification breaks bare `/kunglao-agent`; regression 7f5f179) (D3)
- [x] 4.4 Full suite GREEN: no new failures beyond pre-existing `test_acceptance_overall_passes` + `test_contract_docs::test_skill_lte_500_lines` (also: `git rm` of the tracked `.claude-plugin/` — root cause was IN the repo, not local-only as diagnosed)

## 5. Verify

- [x] 5.1 `python -m pytest tests/test_skill_invocation.py -q` all pass
- [x] 5.2 Full suites: `python -m pytest tests/ scripts/ -q` → pass apart from the pre-existing 2 failures UNCHANGED
- [x] 5.3 Manual greps: `grep -n "arguments:\|argument-hint:" SKILL.md` → 2 hits; `grep -n '\$ARGUMENTS' SKILL.md` → ≥1 hit; `ls .claude-plugin` → not found
- [x] 5.4 `npx.cmd --yes openspec validate` RC=0 ("is valid")
- [x] 5.5 Confirm untouched: DESIGN.md, references/*, hooks/*, scripts/*, agents/*, memory/, rules/, templates/, eval/, the 2 pre-existing test failures

## 6. Commit + PR

- [x] 6.1 Commit SDD artifacts FIRST: `sdd(skill-loader-arguments): proposal/design/spec/tasks for issue #90`
- [x] 6.2 Commit RED tests: `test(skill-invocation): RED — frontmatter arguments + body consumption + no .claude-plugin tests (#90)`
- [x] 6.3 Commit GREEN: `feat(skill): plain-skill invocation with workspace argument — arguments/argument-hint + $ARGUMENTS consumption + deploy note (#90)`
- [x] 6.4 Push branch `feat/skill-loader-arguments`, `gh pr create --base dev` (title `feat(skill): skill loader + arguments — plain-skill invocation with workspace parameter (#90)`) with RED→GREEN evidence
- [ ] 6.5 Do NOT merge / close / push to dev; orchestrator verifies first (maker-checker)
