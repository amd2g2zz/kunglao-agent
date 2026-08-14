# Tasks — skill arguments intent contract (#93)

## 1. Setup

- [x] 1.1 Worktree wt93 on branch `feat/skill-arguments-intent-contract` at dev baseline `2d695a8` (one issue / one branch / one worktree)
- [x] 1.2 Read issue #93 in full: user correction (parameter = user request / subcommand, NOT workspace) + root-cause (SKILL.md `## Arguments` encodes workspace rule; frontmatter declares `[workspace]`; tests guard the wrong semantics)
- [x] 1.3 Grep ground truth: SKILL.md frontmatter (current `arguments: [workspace]` L40-41), `## Arguments` section L253-262 (workspace rule), README for workspace-parameter mentions, scripts/kunglao.py subcommand surface (`decide`/`tick`/`verify`/`record`/`health`)

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 proposal.md (why: user verbatim + workspace-rule baseline; what: frontmatter request semantics, Arguments intent contract, tests rewrite, README sync)
- [x] 2.2 design.md (D1 frontmatter `arguments: [request]`; D2 two-form intent contract — subcommand table + keyword mapping + workspace-never-a-parameter + empty→analysis; D3 RED-first tests; D4 README sync; D5 verification)
- [x] 2.3 specs/skill-arguments-intent-contract/spec.md (ADDED requirements: request-argument frontmatter / body consumes request as subcommand-or-need / no .claude-plugin + README forbid / regression tests)
- [x] 2.4 tasks.md
- [x] 2.5 `openspec validate` PASS (RC=0; use `npx.cmd --yes openspec` — the `new change` scaffold is broken in this environment, manual layout only)
- [x] 2.6 Commit openspec artifacts FIRST: `sdd(skill-arguments-intent-contract): proposal/design/spec/tasks for issue #93`

## 3. RED tests (write first, must fail) — tests/test_skill_invocation.py

- [x] 3.1 `test_skill_frontmatter_declares_request_argument`: parse SKILL.md frontmatter (yaml) → `arguments` key contains `request`, does NOT contain `workspace`; `argument-hint` references `request`
- [x] 3.2 `test_skill_body_arguments_intent_contract`: SKILL.md body `## Arguments` section references `$ARGUMENTS`, lists subcommands `init`/`analysis`/`verify`/`resume`, states the natural-language mapping rule (keyword → subcommand), states workspace-is-never-a-parameter, states empty→`analysis` default
- [x] 3.3 `test_repo_has_no_claude_plugin_dir`: repo root has no `.claude-plugin/` directory (kept from #90)
- [x] 3.4 Confirm RED: `python -m pytest tests/test_skill_invocation.py -q` fails on 3.1/3.2 (baseline says `workspace`; 3.3 passes trivially — it guards the future, RED evidence is 3.1/3.2)

## 4. GREEN implementation

- [x] 4.1 SKILL.md frontmatter: `arguments: [request]` + `argument-hint: [request]` (replace `[workspace]`; `workspace` disappears from the argument surface)
- [x] 4.2 SKILL.md `## Arguments` section rewritten to the two-form intent contract (subcommand table incl. init/analysis/verify/resume + mechanical passthrough; keyword mapping for natural-language requests; workspace-never-a-parameter sentence; empty→analysis default). Keep position (directly before `## Local defaults`) and `$ARGUMENTS` consumption
- [x] 4.3 README: fix any invocation/deployment text that presents a workspace parameter (keep the no-`.claude-plugin/` plain-skill note from #90)
- [x] 4.4 Confirm GREEN: `python -m pytest tests/test_skill_invocation.py -q` all pass
- [x] 4.5 Commit: `feat(skill): arguments intent contract — subcommand/request parameter, workspace auto-detection (#93)`

## 5. Verify & merge

- [ ] 5.1 Full suite (scripts/ + tests/): no new failures beyond the 2 pre-existing (`test_acceptance_overall_passes`, `test_contract_docs::test_skill_lte_500_lines`)
- [ ] 5.2 `openspec validate` PASS on the change
- [ ] 5.3 Orchestrator maker-checker: independent diff review + novel smoke (Arguments section encodes subcommand semantics, not just the heading)
- [ ] 5.4 PR to dev (`feat/skill-arguments-intent-contract`), squash merge, issue #93 close with verification comment
- [ ] 5.5 Cleanup: `git worktree remove --force`, `git branch -D`, dev-clone `git merge --ff-only origin/dev`
- [ ] 5.6 Deployment sync: per-file copy of changed files (SKILL.md, README.md, tests/test_skill_invocation.py) to `~/.claude/skills/kunglao-agent/` (NO git checkout/reset — skills super-repo rule), commit checkpoint
