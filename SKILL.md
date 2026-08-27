---
name: kunglao-agent
description: >-
  Use when the user runs, starts, dispatches, or continues kunglao-agent
  (/kunglao-agent), or when a malware / RE sample needs deep analysis with
  unresolved claims. Also auto-triggers on the user's problem phrases — Chinese
  OR English: "kunglao-agent 笨了", "傻等", "空转", "不收敛", "方法错了", "分析办法有问题",
  "失败归因", "实际进度和计划不匹配", "kunglao-agent stuck / not moving", "plan doesn't
  match reality", "worker reports problem / 卡住", "VM 网络不通", "should just ping".
  Command router: prints the subcommand menu on no args and routes to the
  per-command skills under skills/ (init / analysis / resume / upgrade / help).
  The full convergence contract lives in skills/kunglao-agent/SKILL.md.
triggers:
  - run kunglao-agent
  - continue kunglao-agent
  - start kunglao-agent
  - /kunglao-agent
  - run RE orchestrator
  - deep RE
  - fact base convergence
  - deep analysis
  - run malware analysis
  - orchestrator loop
  - 实际进度和计划不匹配
  - worker reports problem
  - VM 网络不通
  - should just ping
  - RE orchestrator
  - run the RE loop
arguments: [request]
argument-hint: init <workspace> | analysis <workspace> | resume <workspace> | upgrade <workspace> | help
---

# kunglao-agent — command router

This is the entry-point router for the kunglao-agent plugin (skill-dir install
path). It dispatches to the per-command skills under `skills/`. The full
operative contract (convergence loop, failure gates, dispatch mechanics) lives
in `skills/kunglao-agent/SKILL.md` — read that file for the complete behavior.

## No arguments → menu, WAIT

An empty `$ARGUMENTS` prints the subcommand menu below and STOPS — never
silently run the loop. The operator must pick a subcommand.

```
kunglao-agent subcommands:

  /kunglao-agent:init      <workspace> [--type windows|linux|android|web|macos]
                           initialize a workspace (scaffold + CLAUDE.md +
                           sample mount + task_spec intake + hooks)
                           example: /kunglao-agent:init ~/cases/synth-dropper --type windows

  Web environments (`--type web`): labs positioning, docker-default channel,
  camoufox-reverse MCP for browser JS reverse engineering. Quick reference:
  references/re-library/web-re-quickref.md.

  /kunglao-agent:analysis  <workspace>   (alias: analyze)
                           enter the convergence loop on an initialized
                           workspace
                           example: /kunglao-agent:analysis ~/cases/synth-dropper

  /kunglao-agent:resume   <workspace>
                           crash/reboot recovery: read-only breakpoint brief
                           (health + state + timeline + next step); advises
                           the #461 re-arm chain when the heartbeat is dead
                           example: /kunglao-agent:resume ~/cases/synth-dropper

  /kunglao-agent:upgrade  <workspace> [--dry-run]
                           migrate a legacy workspace's framework scaffold
                           forward to the current skill package (hooks,
                           templates, ALWAYS_ARMED hook state, event vocab,
                           #720 .agent/ metadata). User data is never
                           touched (iron rule; RC=4 on byte drift).
                           example: /kunglao-agent:upgrade ~/cases/synth-dropper

  /kunglao-agent:help      [no args]
                           print this usage list
                           example: /kunglao-agent:help

Next steps:
  uninitialized workspace → /kunglao-agent:init
  initialized workspace   → /kunglao-agent:analysis
  crashed / rebooted ws   → /kunglao-agent:resume
  legacy / behind ws      → /kunglao-agent:upgrade
  unsure which command    → /kunglao-agent:help
  partial arguments       → the subcommand prints its own guided prompt
                           (see its SKILL.md "No arguments" section)
(feat(#413): subcommand UX + guided entry — skills/ layout, menu, hints, README table;
 #456: zero-args guard below the router, per-command examples + next steps —
 menu/hints render skills/subcommands.yaml, the single source)
```


## Routing

`$ARGUMENTS` is consumed as `[subcommand] [args...]`:

- `init <workspace> [--type ...]` → read and follow `skills/init/SKILL.md`.
- `analysis <workspace>` (alias `analyze`) → read and follow
  `skills/analysis/SKILL.md`; the convergence loop is the destination.
- `resume <workspace>` → read and follow `skills/resume/SKILL.md`
  (read-only crash/reboot recovery brief, #466).
- `upgrade <workspace>` → read and follow `skills/upgrade/SKILL.md`
  (forward-only workspace framework-scaffold migration, #726; user data
  read-only per iron rule; pairs with #739 git snapshot).
- `help` → read and follow `skills/help/SKILL.md` (usage list).
- Natural-language RE request (e.g. "what does this binary do") → map to
  `analysis`: read `skills/analysis/SKILL.md` then
  `skills/kunglao-agent/SKILL.md` for the operative contract.
- Unknown subcommand (not in the table, not natural language) → print the menu
  AND `unknown: <x>` — never guess, never silently run.

The workspace is an explicit positional argument. When it is absent the
subcommand runs its guided no-args prompt (see the "No arguments" section of
`skills/init/SKILL.md` and `skills/analysis/SKILL.md`) — never a silent
default, never a guess. `<SKILL_DIR>` is the repo root (this file's parent),
not `skills/kunglao-agent/`.

## Examples

- `/kunglao-agent` — print the subcommand menu, wait for a choice.
- `/kunglao-agent init ~/cases/synth-dropper --type windows`
- `/kunglao-agent analysis ~/cases/synth-dropper`
- `/kunglao-agent resume ~/cases/synth-dropper`
- `/kunglao-agent upgrade ~/cases/synth-dropper`
- `/kunglao-agent help`
(feat(#413): subcommand UX + guided entry — skills/ layout, menu, hints, README table)
