# Proposal — contract hygiene: isolation-first dispatch (Agent-only, TaskStop-on-delivery, no agent team; SendMessage ping retained) (#88)

## Why

The original diagnosis of the "dispatch looks different / zombie workers" regression blamed a harness subagent→agent-team migration; that was wrong. Agent teams are an **experimental, opt-in** feature (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`) and subagents remain the default, inherently isolated model. The real machine-level root cause was the env flag being globally set (already removed, 2026-08-12), and the durable gaps are contract hygiene: (1) the skill body still references the nonexistent `Task` tool (`Agent` is the only dispatch tool); (2) background workers do not exit on delivery, so a delivered worker that is never stopped holds a slot forever (the actual zombie root cause, independent of teams); (3) the isolation-first rule — no agent team, workers = isolated subagents that never message each other — exists only as a user correction and is not written into the contract, so the experimental feature can silently change the dispatch model again. **Scope correction (user, 2026-08-12: "SendMessage我不认为有问题")**: the earlier draft over-applied isolation by also banning SendMessage orchestrator↔worker pings (heartbeat active-ping, v1.9.20/21); SendMessage to/from one's own subagent is the documented continuation channel, not a team feature — it is retained, and only team features are banned.

## What Changes

- **BREAKING (contract) — isolation-first hard rule** lands in `SKILL.md` §1 + §"The dispatch contract", `references/cold-start-contract.md` (Phase 0), and `references/operational-mechanics.md`: kunglao tasks never use agent teams (never enable `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`; no teammates, no team setup, no worker↔worker messaging) — workers are always isolated subagents that report only to the orchestrator; deliverables are files; delivery means TaskStop. SendMessage orchestrator↔worker pings (heartbeat active-ping, v1.9.20/21) are explicitly NOT a team feature and remain the sanctioned channel; file state (`worker-status-*.md`, `[active_workers]`) remains the accounting source of truth.
- **BREAKING (contract) — TaskStop-on-delivery**: the dispatch contract requires the orchestrator to TaskStop a background worker immediately after delivery confirmation (`status: done` + artifacts verified), instead of letting it linger as a zombie slot. Primary enforcement = hard rule in `SKILL.md` §dispatch + a delivery checklist in `references/operational-mechanics.md`; mechanical aid = `hooks/worker_pulse.py` injects a "TaskStop W-<n> now" reminder at the delivery moment (PostToolUse on Agent). Hooks are subprocess commands and cannot invoke Agent/TaskStop tools, so a fully mechanical stop is impossible — the rule is the enforcement, the pulse is the nudge.
- **Heartbeat active-ping retained (SendMessage) + isolation boundary documented**: `references/operational-mechanics.md` tick loop, `references/guardrails.md` §6.1a/§6f.1 full text, `scripts/heartbeat_loop_prompt.py` (generated /loop prompt), `scripts/active_intervention.py` (workaround channel = `## orchestrator_response` in `heartbeat_actions.md`), `scripts/kunglao-monitor.py` helper text, and `agents/kunglao-redteam.md` (verdict via `runs/` report file + dispatch return) — none instruct agent-team setup or worker↔worker messaging; SendMessage ping steps are kept.
- **Stale `Task` tool references removed repo-wide** (Agent is the only dispatch tool). Grep inventory (11 files):

  | File | Stale reference |
  |---|---|
  | `SKILL.md` L305 | "route the remaining work through `Task` dispatches" |
  | `SKILL.md` L307 | table header "Analysis (delegate via Task)" |
  | `hooks/dispatch_gate.py` L6, L18 | docstring "fires on the Task tool" / "PreToolUse hook on Task" |
  | `hooks/dispatch_gate.py` L110-111 | "Older Task-based dispatches…" (payload-shape robustness kept, Task framing dropped) |
  | `references/guardrails.md` L23, L63 | "delegate to a `Task` worker" / "fresh `Task` agent… dispatched via" |
  | `.claude/commands/opsx/archive.md` L65 | "use Task tool (subagent_type: …)" |
  | `.claude/skills/openspec-archive-change/SKILL.md` L69 | "use Task tool (subagent_type: …)" |
  | `agents/*.md` (10 agent definitions) | `disallowedTools: - Task` — dead tool name, removed |

## Capabilities

### New Capabilities

- `isolation-first-dispatch-contract`: the kunglao-agent dispatch contract capability — Agent is the only dispatch tool (no stale Task-tool references), workers run fully isolated (no agent team, no teammate spawns, no worker↔worker messaging; SendMessage orchestrator↔worker pings retained; file state = accounting source of truth; deliverables = files), and a delivered worker is TaskStop'd on delivery confirmation.

### Modified Capabilities

(none — `openspec/specs/` has no existing dispatch-contract spec; this change introduces the first)

## Impact

- Contract text: `SKILL.md` (§1 Tool-use boundary, §"The dispatch contract", §6.1a compact, "Active workers heartbeat"), `references/cold-start-contract.md` (Phase 0), `references/operational-mechanics.md` (heartbeat tick loop documenting retained SendMessage ping + file-state accounting, delivery checklist), `references/guardrails.md` (§6.1a smart-ping full text, §6f.1 watchdog, mid-course-correction lines).
- Code: `hooks/dispatch_gate.py` (comments/docstring only), `hooks/worker_pulse.py` (new TaskStop-on-delivery reminder, RED-tested). `scripts/heartbeat_loop_prompt.py` / `scripts/active_intervention.py` / `scripts/kunglao-monitor.py` are documented only (their SendMessage ping steps are the retained channel; the isolation boundary text is added where needed).
- Agent definitions: `agents/*.md` (10 files — `- Task` disallowedTools removal), `agents/kunglao-redteam.md` (verdict deliverable = `runs/` report file + dispatch return).
- Not touched: `DESIGN.md` (architecture history), `references/re-library/*` (Win32 `SendMessageW` is unrelated), `memory/`, `rules/`, `templates/`, `eval/`.
- Tests: new `tests/test_dispatch_contract.py` — RED first — covering (a) no-stale-Task-tool grep, (b) isolation-first contract text presence in the four landing files, (c) worker_pulse TaskStop-on-delivery reminder, (d) heartbeat prompt keeping SendMessage ping with no team markers. Pre-existing failures (`test_acceptance_overall_passes`, `test_skill_lte_500_lines`) unchanged.
