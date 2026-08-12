# Proposal — skill arguments: parameter is the user REQUEST (subcommand | natural-language need), not a workspace path (#93)

## Why

User correction (2026-08-12, verbatim): "参数不对 参数用户的需求或者子命令（init|analysis等等） 而不workspace".

Issue #90 (PR #92, dev 2d695a8) defined the `/kunglao-agent <arg>` parameter as a **workspace path** — frontmatter `arguments: [workspace]` and the body's `## Arguments` section say "the first argument is the workspace path". The user explicitly corrects the semantics: the parameter is the **user's request** — either a **subcommand** (`init` / `analysis` / `verify` …) or a **natural-language need**; workspace must NOT be a parameter. Workspace detection stays in Phase 0 (Local defaults / workspace pattern).

Current facts (dev 2d695a8):
- `scripts/kunglao.py` already exposes a unified CLI with subcommands `decide` / `tick` / `verify` / `record` / `health` (M1/M5/M3/M4 mechanical ops).
- CLI family also has `kunglao-init.py` (workspace init), `kunglao-monitor.py`, `kunglao-digest.py`, `kunglao-eval.py`.
- SKILL.md `## Arguments` (L253-262) currently encodes the wrong workspace rule — must be rewritten.
- tests/test_skill_invocation.py guards the wrong semantics (asserts `arguments` includes `workspace`, asserts "first argument is the workspace path").

## What Changes

- **SKILL.md frontmatter**: `arguments: [workspace]` / `argument-hint: [workspace]` → `arguments: [request]` / `argument-hint: [request]` — the named argument is the user REQUEST (subcommand or natural-language need).
- **SKILL.md `## Arguments` section**: rewritten intent contract —
  1. **Subcommand** (exact, case-insensitive): `init` (Phase 0 workspace init) / `analysis` (alias `analyze`; enter the convergence loop; default) / `verify [fact_id]` (M3 verify chain only) / `resume` (alias `continue`; idempotent continuation) / mechanical CLI passthrough `decide` `tick` `record` `health` `monitor` `digest` `eval`.
  2. **User request** (anything else): map by intent keywords → subcommand (初始化/工作区→init; 分析/继续分析/收敛/循环/deep analysis→analysis; 验证/verify F-NNN→verify; 健康/状态→health; unrecognized→analysis).
  3. **Empty** → analysis (the default convergence loop).
  Workspace is NEVER a parameter — Phase 0 detection is unchanged (Local defaults table).
- **tests/test_skill_invocation.py**: rewrite 3 tests to the intent contract — (a) frontmatter declares `request` (not `workspace`); (b) Arguments section contains the subcommand set (init/analysis/verify/resume), the natural-language mapping rule, and the workspace-auto-detection statement; (c) no `.claude-plugin/` (kept from #90).
- **README.md**: fix any mention of a workspace parameter (deployment/usage text), mirroring the new intent contract.

## Out of Scope

- No change to `scripts/kunglao.py` or the CLI family — they already expose the subcommand surface; this change only fixes the SKILL.md invocation contract that maps the skill parameter onto it.
- No behavior change to Phase 0 workspace auto-detection logic.
