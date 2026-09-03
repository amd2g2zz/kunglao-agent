## 1. Setup

- [x] 1.1 Branch `v012/issue-456-subcommand-ux` off `dev` baseline 6462fe4 (one issue / one PR / one branch / one worktree `D:/works/kunglao-wt/456`)
- [x] 1.2 Baseline quick gate recorded: `uv run --project . python -m pytest -q -m "not load_sensitive"` before any change

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 proposal.md (why: guard-below-router gap, router self-contradiction, hint/menu thinness — #456 evidence 1-3)
- [x] 2.2 design.md (D1 zero-args prescribed actions / D2 #455 routing + decision_pending concept / D3 workspace = explicit positional / D4 subcommands.yaml single source + lint / D5 hint enrichment; R1-R5 rejected)
- [x] 2.3 tasks.md

## 3. RED tests (write first, must fail)

- [x] 3.1 Registry: `skills/subcommands.yaml` exists, parses, covers init/analysis/help with all six fields (invocation / argument-hint / zero-args / missing-args / example / next-step)
- [x] 3.2 Render lint A: root SKILL.md menu carries every registry invocation + example + next-step lines and the shared next-steps guidance
- [x] 3.3 Render lint B: each subcommand frontmatter `argument-hint` equals the registry hint exactly
- [x] 3.4 Render lint C: README Command Reference covers every registry command with matching args cell
- [x] 3.5 Zero-args defined: init + analysis SKILL.md have a no-args section with guided-prompt action + never-guess/no-bare-error guards; help no-args pinned
- [x] 3.6 Partial args defined: init missing `--type` routes to the #455 intake sequence (no silent default); analysis missing workspace = guided prompt with cwd-confirm
- [x] 3.7 Contradiction removed: "never a parameter" in NO SKILL.md; the explicit-positional-argument anchor sentence present in BOTH root router and main contract
- [x] 3.8 Hint enrichment: analysis hint carries alias `analyze` + no-args guidance; init hint carries no-args guidance
- [x] 3.9 Confirm RED: `python -m pytest tests/test_subcommand_zeroarg_ux.py -q` fails on baseline; commit RED hash recorded

## 4. GREEN — docs as the implementation

- [x] 4.1 `skills/subcommands.yaml` — the registry (D4)
- [x] 4.2 Root `SKILL.md` — menu examples + Next steps block; D3 sentence swap (D3/D5)
- [x] 4.3 `skills/init/SKILL.md` — No arguments + Missing --type sections (#455 routing); hint (D1/D2/D5)
- [x] 4.4 `skills/analysis/SKILL.md` — No arguments / missing workspace section (cwd-confirm rule); hint with alias (D1/D5)
- [x] 4.5 `skills/help/SKILL.md` — no-args statement pinned (D1)
- [x] 4.6 `skills/kunglao-agent/SKILL.md` — Arguments sentence swap + Phase 0 step 5 retitle to workspace resolution, semantics only (D3)
- [x] 4.7 `README.md` — Command Reference rows match the registry (D4)

## 5. REFACTOR + gates

- [x] 5.1 REFACTOR pass over the test file (helpers mirroring test_skill_subcommand_ux.py, no duplication creep) and doc wording consistency; rerun
- [x] 5.2 File gate: `uv run --project . python -m pytest tests/test_subcommand_zeroarg_ux.py tests/test_skill_subcommand_ux.py -q` green (new contract coexists with #413's)
- [x] 5.3 Quick gate: `uv run --project . python -m pytest -q -m "not load_sensitive"` green (#369 filter mandatory)
- [x] 5.4 RED-hash replay sanity: the RED commit checks out and its test run is red (recorded in RUNBOOK)

## 6. Deliverables

- [x] 6.1 `.review/RUNBOOK.md` — change list / checkbox-to-test map / risks / RED hash / gate tail lines
- [x] 6.2 Commits: `sdd(issue-456): ...` / `test: RED ... (#456)` / `feat: ... (#456)` (no push, no PR — orchestrator owns Task 5)
