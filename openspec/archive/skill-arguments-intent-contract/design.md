# Design — skill arguments intent contract (#93)

## D1: frontmatter declares the request argument

`arguments: [request]` + `argument-hint: [request]` replace `[workspace]`. Rationale: the loader's named-argument surface must mirror the parameter's actual semantics — the user request (subcommand or natural-language need). `request` is the stable name the model should interpolate (`$request`); `$ARGUMENTS` remains the positional fallback for both forms. `workspace` disappears from the argument surface entirely — no user should be invited (via hint/autocomplete) to pass a path.

## D2: `## Arguments` intent contract (body)

The section (positioned where the current `## Arguments` sits, directly before `## Local defaults`) is rewritten as a two-form contract:

1. **Subcommand** — exact, case-insensitive match against the set:
   | subcommand | alias | behavior |
   |---|---|---|
   | `init` | — | Phase 0 workspace initialization (scaffold + sample mount + task_spec intake + hooks) |
   | `analysis` | `analyze` | enter the convergence loop (dispatch/verify/update) — the default for unrecognized input and empty `$ARGUMENTS` |
   | `verify [fact_id]` | — | run only the M3 verify chain (L1 mechanical + L2 redteam) |
   | `resume` | `continue` | idempotent continuation of an existing workspace (no re-scaffold) |
   | `decide` `tick` `record` `health` `monitor` `digest` `eval` | — | mechanical CLI passthrough to the kunglao CLI family (scripts/kunglao.py subcommands) |

2. **User request** — anything not matching a subcommand: map by intent keywords to a subcommand:
   - 初始化 / 工作区 / scaffold / init → `init`
   - 分析 / 继续分析 / 收敛 / 循环 / deep analysis / analyze / run → `analysis`
   - 验证 / verify / F-NNN → `verify`
   - 健康 / 状态 / monitor / health → `health`
   - unrecognized → `analysis`

3. **Empty** `$ARGUMENTS` → `analysis` (the default loop).

**Workspace is never a parameter.** One explicit sentence: workspace detection always runs in Phase 0 per the Local defaults table (workspace pattern), regardless of the request form.

## D3: tests — intent contract regression (RED-first)

Rewrite tests/test_skill_invocation.py (3 tests, same file, same structure as #90):

- `test_skill_frontmatter_declares_request_argument`: frontmatter `arguments` present, contains `request` (or `subcommand`), and does **NOT** contain `workspace`; `argument-hint` mirrors it.
- `test_skill_body_arguments_intent_contract`: `## Arguments` section exists and asserts — (a) subcommand set members `init` and `analysis` present; (b) `verify` + `resume` present; (c) natural-language mapping rule stated (keyword → subcommand); (d) workspace-not-a-parameter rule stated; (e) empty → default analysis rule stated.
- `test_repo_has_no_claude_plugin_dir`: unchanged from #90 (guards 7f5f179 regression).

RED on current baseline: all three fail — frontmatter says `workspace`, Arguments section says "first argument is the workspace path", and neither subcommand set nor mapping rule exists.

## D4: README sync

README deployment/usage text that mentions the workspace parameter is corrected to the request contract (`/kunglao-agent [init|analysis|verify|resume|...]` or a natural-language need). The plain-skill deployment note (no `.claude-plugin/`) from #90 stays untouched.

## D5: verification

- `openspec validate` must pass ("is valid") in the change dir.
- 3 tests RED on baseline → GREEN after SKILL.md edit.
- Full suite: no new failures beyond the 2 pre-existing (test_acceptance_overall_passes / test_skill_lte_500_lines).
- Orchestrator novel smoke: independent check that the Arguments section text actually encodes subcommand semantics (not just presence of the heading).
