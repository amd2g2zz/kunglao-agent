# Subagent hook-semantics probe (#779 face one) — verdict (a)

- **Date**: 2026-10-19
- **Runner**: T1 observation engineer (feat/779-observation worktree)
- **Question**: do Task-spawned subagent sessions fire the workspace PreToolUse/PostToolUse hook battery (issue #779 Face 1: "verify Claude Code's subagent hook semantics")?
- **Verdict**: **(a) — fires, but incompletely attributed.** The worker's tool calls DO fire the workspace hooks on CLI 2.1.270. The gap is ATTRIBUTION, not firing: the payloads carry the PARENT `session_id`, with the worker identity riding `agent_id`/`agent_type`.

## Method

1. Synthetic workspace `ws/` with a minimal `.claude/settings.json` wiring every hook event to a shell append (`tee -a`), one log file per event (PreToolUse / PostToolUse / Stop / SubagentStop / SessionStart). No repo code involved — the wiring pattern mirrors the deployed project-scoped hook registration (`<ws>/.claude/settings.json`, `scripts/wire_up_settings.py` #258).
2. One headless session: `claude -p "<run one Bash command; then spawn a general-purpose Task subagent that runs one Bash command>" --model haiku --allowedTools "Bash,Task"` with cwd = the synthetic workspace.
3. Parse the event logs: tool names, per-event payload fields, session/agent identity.

## Raw evidence

- Probe workspace + event logs: `/tmp/kunglao-hook-probe/` (`events-PreToolUse.jsonl`, `events-PostToolUse.jsonl`, `events-Stop.jsonl`, `events-SubagentStop.jsonl`, `events-SessionStart.jsonl`, and `ws/.claude/settings.json`).
- Session transcript: `/Users/mikenike/.claude/projects/-private-tmp-kunglao-hook-probe-ws/2c5c41e6-e248-4d62-b34e-e97f5f8ea654.jsonl`
- CLI: Claude Code 2.1.270 (headless `-p`, permission mode `default`, tools allow-listed).

## Findings (from the raw payloads)

1. The subagent's Bash call (`echo probe-subagent-marker`) produced BOTH a PreToolUse and a PostToolUse row in the workspace logs — the hooks fire for Task-subagent tool calls.
2. Attribution: the subagent's rows carry `"agent_id": "a2c7febc4c2128560"`, `"agent_type": "general-purpose"`, but `"session_id"` = the PARENT session (`2c5c41e6-…`), same as the orchestrator's own calls. Parent-session rows carry NO `agent_id` key.
3. `SubagentStop` fired once with the same parent `session_id` and additionally `agent_id`, `agent_type`, `agent_transcript_path` (`…/<session>/subagents/agent-<agent_id>.jsonl`).
4. Reconciling with the #779 campaign blindness (zero worker-side step-ledger rows): the campaign ran an older CLI where the firing itself was absent, and workspace resolution (`resolve_ws` cwd scan) is the second precondition — hooks only load from the SESSION's project settings, so a session whose cwd is not the workspace never loads them at all. Both preconditions are deployment facts; on the current CLI with correct cwd, firing is proven.

## Fix implemented (the (a) path)

The inheritance gap is the identity, so the observation faces became agent-aware (no Claude-Code-side change is possible from the repo):

- `hooks/step_record_capture.py` — thread the payload's `agent_id`/`agent_type` into `build_step_row`; rows carry the worker identity when present.
- `scripts/rlvr/step_ledger.py` — `step-record/1` whitelist grows `agent_id`/`agent_type` (additive: keys appear only when an identity exists); `step-record/2` grows `agent_id`; `read_step_grains` scopes by agent.
- `scripts/rlvr/step_grain.py` — `aggregate_session_steps` / `settle_step` / `step_id_for` scope by agent: an agent settle aggregates ONLY that agent's rows; the parent bucket (no agent) EXCLUDES agent-tagged rows (no double-counting across stops); step ids are deterministic in (session, agent, ordinal).
- `hooks/round_closure.py` — the SubagentStop payload's `agent_id` threads into the settle face.

The (b) path (orchestrator-side transcript extraction) is NOT needed on this CLI; the `agent_transcript_path` field documented here is the ready seam if a future CLI regresses.
