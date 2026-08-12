# Tasks — isolation-first dispatch contract (#88)

## 1. Setup

- [x] 1.1 Worktree wt88 on branch `feat/isolation-first-contract` at dev baseline `f0e0634` (one issue / one branch / one worktree)
- [x] 1.2 Read issue #88 in full: agent-team is experimental + opt-in; machine-level flag `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` removed (2026-08-12); 3 scope items + acceptance criteria. **Scope correction (2026-08-12 user: "SendMessage我不认为有问题")**: SendMessage orchestrator↔worker pings are retained (not a team feature); only team features are banned.
- [x] 1.3 Grep inventory complete: 11 files with stale `Task` tool references (SKILL.md L305/L307, hooks/dispatch_gate.py L6/L18/L110-111, references/guardrails.md L23/L63, .claude/commands/opsx/archive.md L65, .claude/skills/openspec-archive-change/SKILL.md L69, agents/*.md ×10 `- Task`); SendMessage transport inventory complete (heartbeat_loop_prompt.py, active_intervention.py, kunglao-monitor.py, kunglao-redteam.md, guardrails.md, operational-mechanics.md — these KEEP their SendMessage ping steps)
- [x] 1.4 Read-only ground truth: `hooks/worker_pulse.py` (fires PostToolUse on Agent = delivery moment), `hooks/dispatch_gate.py` (payload-shape robustness), `scripts/reconcile_workers.py` (done workers already excluded from active_workers), `scripts/active_intervention.py` (`## orchestrator_response` file channel already parsed), `scripts/heartbeat_loop_prompt.py` (SendMessage ping line), `references/operational-mechanics.md` + `references/guardrails.md` §6.1a/§6f.1 (heartbeat protocol homes); precedent `openspec/changes/stuck-worker-gate/` + `distill-heldout-eval-gate/` (house style)

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 `openspec new change isolation-first-dispatch-contract` scaffolded (schema spec-driven)
- [x] 2.2 proposal.md (why: misdiagnosed team migration → real root cause = env flag + contract hygiene; scope (a) stale Task refs with full grep inventory, (b) TaskStop-on-delivery, (c) isolation-first in 4 landing points; capabilities; impact)
- [x] 2.3 design.md (D1-D6: TaskStop rule + worker_pulse delivery reminder, retained SendMessage heartbeat ping with file-state accounting, isolation-first four landing points, stale-ref exact edits, isolation scope boundary, RED test strategy; risks/migration)
- [x] 2.4 specs/isolation-first-dispatch-contract/spec.md (REQ ×5: Agent-only dispatch / isolation-first hard rule (no team; SendMessage ping allowed) / heartbeat SendMessage ping + file-state accounting / TaskStop-on-delivery / regression tests)
- [x] 2.5 tasks.md
- [x] 2.6 `openspec validate` PASS ("is valid")
- [x] 2.7 Commit openspec artifacts FIRST: `sdd(isolation-first-dispatch-contract): proposal/design/spec/tasks for issue #88`
- [x] 2.8 SDD revision commit: `sdd(isolation-first-dispatch-contract): revise — SendMessage orchestrator↔worker ping retained, team features only banned; monitor runs in background` (user corrections 2026-08-12: "SendMessage我不认为有问题" → scope narrowed from file-only comms to team-feature ban only; "monitor应该在后台运行" → kunglao-monitor.py runs as a background process, never blocking the loop's scheduled tick actions)

## 3. RED tests (write first, must fail) — tests/test_dispatch_contract.py

- [x] 3.1 `test_no_stale_task_tool_references`: repo-wide grep over SKILL.md / references/ / hooks/ / scripts/ / agents/ / .claude/ for `Task tool`, backtick `` `Task` ``, `- Task` tool entry → 0 hits; TaskStop/TaskList/task_spec/task-oracle untouched
- [x] 3.2 `test_skill_dispatch_contract_isolation_first`: SKILL.md §1 + §"The dispatch contract" contain all four markers: no-agent-team (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` never enabled / no teammates / no team setup), workers-never-message-each-other, SendMessage-orchestrator↔worker-ping-allowed, TaskStop-on-delivery
- [x] 3.3 `test_cold_start_contract_isolation_first`: references/cold-start-contract.md Phase 0 contains the rule + flag root-cause note
- [x] 3.4 `test_operational_mechanics_isolation_first`: references/operational-mechanics.md contains the "Delivery = TaskStop" checklist, keeps the SendMessage ping step in the heartbeat procedure, and contains no agent-team instructions
- [x] 3.5 `test_worker_pulse_taskstop_reminder`: worker_pulse on a dispatch-completion payload with fixture `status: done` file → output contains `TASKSTOP:`; `in-progress` fixture → no reminder
- [x] 3.6 `test_heartbeat_prompt_sendmessage_allowed`: heartbeat_loop_prompt.py output KEEPS the SendMessage ping step and contains no agent-team markers (no `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`, no teammates, no team setup)
- [x] 3.7 `test_redteam_agent_no_team_features`: agents/kunglao-redteam.md has no `- Task` disallowedTools entry and no agent-team wording (SendMessage not instructed, not banned)
- [x] 3.8 Confirm RED: `python -m pytest tests/test_dispatch_contract.py -q` fails on the new tests
- [x] 3.9 `test_monitor_background_note`: references/operational-mechanics.md (or SKILL.md) states kunglao-monitor.py runs as a BACKGROUND process — it never blocks the loop's scheduled tick actions (re-dispatch / verify)

## 4. GREEN implementation

- [x] 4.1 SKILL.md: L305 `Task` → `Agent`; L307 table header "delegate via Agent"; isolation-first bullet in §1; isolation-first subsection + TaskStop-on-delivery rule in §"The dispatch contract" (D1/D3)
- [x] 4.2 references/cold-start-contract.md Phase 0: isolation-first statement + flag root-cause cautionary note (D3)
- [x] 4.3 references/operational-mechanics.md: heartbeat tick loop documents the retained SendMessage ping (orchestrator→worker, smart-ping) + file-state accounting + 3-strike table; new "Delivery = TaskStop" section (D1/D2); new "monitor runs in background" note — kunglao-monitor.py is a background process, never blocking the loop's scheduled tick actions
- [x] 4.4 references/guardrails.md: §6.1a smart-ping full text, §6f.1 watchdog, mid-course-correction lines keep SendMessage ping + state the isolation boundary (no team features) (D2/D5); L23/L63 `Task` → `Agent` (D4)
- [x] 4.5 hooks/dispatch_gate.py: docstring/comments `Task` → `Agent`; L110-111 keep payload robustness, drop Task framing (D4)
- [x] 4.6 hooks/worker_pulse.py: TASKSTOP delivery reminder when completed worker's status file shows final state (D1)
- [x] 4.7 scripts/heartbeat_loop_prompt.py: generated prompt KEEPS the SendMessage ping step (orchestrator→worker) + adds no team markers (D2)
- [x] 4.8 scripts/active_intervention.py option (a) + docstring + scripts/kunglao-monitor.py helper text: keep `## orchestrator_response` file channel, add isolation-boundary note (no team features) + monitor-background note (D2/D5)
- [x] 4.9 agents/*.md (10 files): remove `disallowedTools: - Task`; agents/kunglao-redteam.md L105: verdict delivered via `runs/` report file + dispatch return (SendMessage permitted, not instructed) (D3/D4)
- [x] 4.10 .claude/commands/opsx/archive.md L65 + .claude/skills/openspec-archive-change/SKILL.md L69: "Task tool" → "Agent tool" (D4)
- [x] 4.11 Full suite GREEN: no new failures beyond pre-existing `test_acceptance_overall_passes` + `test_skill_lte_500_lines`

## 5. Verify

- [x] 5.1 `python -m pytest tests/test_dispatch_contract.py -q` all pass
- [x] 5.2 Full suites: `python -m pytest tests/ scripts/ -q` → pass apart from the pre-existing 2 failures UNCHANGED
- [x] 5.3 Manual grep cross-check: `grep -rn "Task tool\|`Task`\|- Task$" SKILL.md references/ hooks/ scripts/ agents/ .claude/` → 0 hits; `grep -rn "SendMessage" scripts/heartbeat_loop_prompt.py agents/kunglao-redteam.md references/operational-mechanics.md` → ≥1 hit each (ping retained); `grep -rn "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS" SKILL.md references/` → only as never-enable prohibition
- [x] 5.4 `openspec validate` PASS (final, "is valid")
- [x] 5.5 Confirm untouched: DESIGN.md (history-only), references/re-library/*, memory/, rules/, templates/, eval/, `test_acceptance_overall_passes` / `test_skill_lte_500_lines` failure status

## 6. Commit + PR

- [x] 6.1 Commit SDD artifacts FIRST: `sdd(isolation-first-dispatch-contract): proposal/design/spec/tasks for issue #88`
- [x] 6.2 Commit RED tests: `test(isolation): RED — dispatch contract isolation-first + TaskStop-on-delivery tests (#88)`
- [x] 6.3 Commit GREEN: `feat(contract): isolation-first dispatch — Agent-only, no team features, TaskStop-on-delivery; SendMessage ping retained (#88)`
- [x] 6.4 Push branch `feat/isolation-first-contract`, `gh pr create --base dev` (title `feat(contract): isolation-first dispatch contract hygiene (#88)`) with RED→GREEN evidence
- [x] 6.5 Do NOT merge / close / push to dev; orchestrator verifies first (maker-checker)
