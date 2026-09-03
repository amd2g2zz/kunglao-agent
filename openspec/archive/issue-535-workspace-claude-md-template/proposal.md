# Change: workspace CLAUDE.md 模板 — 渐进披露 + memory 契约 + loop 强制块 (#535)

## Why

The workspace CLAUDE.md template had grown into a 136-line body that
embedded state inline: workers read the template body instead of following
pointers (defeating progressive disclosure, F-C1) and the convergence-loop
rules lived only in prose that did not survive context compact (F-C2,
confirmed gap in the #531 deep review).

## What changes

- Core cold-start section (everything above `## State files`) reduced to
  ≤50 lines — 37 lines as landed, test-asserted
  (`tests/test_workspace_claude_md_template_535.py`).
- A 9-row pointer table (`## Workspace at a glance`) replaces inline state:
  analysis_state / global_plan / task_spec / claim-register / claim_deps /
  facts/_INDEX / blockers/ / runs/ / runs/.env-check.json.
- `## Loop enforcement (persistent channel)` block names per-round
  convergence_check, heartbeat TTL (35 min, matching
  `scripts/heartbeat.py` STALE_MINUTES), task-oracle verdict, post-compact
  re-entry — the only convergence channel that survives compact.
- `## Memory carriers (write/recall contract)`: 6-carrier table
  (claim-register, facts/_INDEX+F<NNN>, blockers/, global_plan,
  analysis_state, task-oracle) with write-what / who-writes-when /
  when-recall / correction-semantics per carrier. Carriers match what init
  actually scaffolds (#538 SCAFFOLD_DIRS + #473 task-oracle skeleton).
- `**Write criteria**` (5 criteria; replacement test = criterion 4, HARD)
  + `**When to skip a write**` list replaces blanket write directives
  (C-2 anti-pattern).
- `## Sample under analysis` moved below `## State files` (identity is
  dynamic state; the core carries pointers only).
- Golden fixtures regenerated (template body legitimately changed;
  sentinel inputs unchanged).

## Impact

- Affected specs: NEW `workspace-claude-md` capability.
- Affected code: `templates/CLAUDE.md.base.tmpl` +
  `tests/fixtures/claudemd-golden/{windows,linux,android}.md` (regen).
- No init-script behavior change; render path (`write_claudemd` ->
  `template_render.render_strict`) unchanged; #536 version stamp still
  lands post-render.
- BLIND verifier contract wording preserved (and made explicit).
- Out of scope per user decision: AGENTS.md bridge (NOT created), #533
  SessionStart injection, #534 init logging.

## Acceptance

- Core section ≤50 lines, no dynamic state inline (pytest-guarded).
- All 9 pointers render verbatim and resolve after a real init run
  (on-demand pair — task_spec.yaml, runs/.env-check.json — carries its
  creator in the pointer row; F-473 lesson).
- Loop-enforcement block present with all four mandatory rules.
- 6-carrier contract table present; no blanket write-disable phrases.
- BLIND verifier wording preserved.
- No issue numbers in the template body (template never feeds SKILL.md,
  but the body stays clean regardless).
- Full suite: zero new failures (2 pre-existing worktree-caused failures
  proven at pristine HEAD).
