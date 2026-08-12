# Tool inventory & CLI family

> Extracted from SKILL.md for progressive disclosure. Consult when you need to know
> which scripts/MCP tools are available and what the kunglao CLI family looks like.

## What's available (an inventory, not a recipe)

The skill ships with these tools. They are not instructions to use; they
are a toolshelf. The right time to pick up a tool is when you recognize
the situation it was built for.

| Tool | When it was built for |
| --- | --- |
| `scripts/convergence_check.py` | **Every turn, before anything else** — answers "should I dispatch, or am I converged/saturated/blocked?" |
| `scripts/convergence_health.py` | **Every 3rd turn / when "busy but stuck"** — reads the ledger and answers "is the loop actually converging, or spinning?" |
| `scripts/failure_analysis_gate.py` | **When a worker reports failure, before re-dispatch or NEGATIVE** — forces 3-question method-failure reasoning. A failed attempt is not evidence the behavior is absent |
| `scripts/priority.py` | "I have multiple open claims and need to pick the next one" — value/leverage/cheapness scoring |
| `scripts/active_intervention.py` | "A worker has been silent for > 5 min and the status file shows it's stuck" — non-response is a signal |
| `scripts/backtrack_gate.py` | "The same worker has been doing the same thing for > 20 min without progress" — backtrack decision required |
| `scripts/doubt_checker.py` | "I'm about to declare a claim PROVEN-FULL" — independent verifier sign-off is structural |
| `scripts/stale_blocker_prune.py` | "A claim is terminal but its blocker file is still in the active directory" |
| `scripts/claim_expiry.py` | "I have an OPEN claim with no activity for > 24 hours" — flag as STALE, don't auto-defer |
| `scripts/progress_report.py` | "I want to see at a glance where the loop is" — emit a single markdown block |
| `scripts/plan_drift_detector.py` | "I re-planned / decomposed / abandoned claims since the last plan-file edit" — **v1.9.29 (mechanical)**: `worker_budget.py` PreToolUse REJECTS any dispatch on detected drift (exit ≥1) |
| `scripts/hook_activation.py` | "I want some of the gates to pause (HARD_PAUSE tier)" — selective activation |
| `hooks/worker_pulse.py` | PostToolUse hook — auto-injects the convergence snapshot when a worker completes (so you can't forget the check) |
| `scripts/ask_for_direction_gate.py` | "I just emitted text as the orchestrator" — scan for反问 patterns |
| `mcp__context7-mcp__resolve-library-id` + `get-library-docs` | "I'm about to dispatch a worker for an API/struct I don't fully know" |
| `mcp__sequential-thinking` | "This decision has 3+ steps with branching logic" |
| `mcp__web_reader__webReader` | "I need clean markdown from an external URL" |

### kunglao CLI family (unified surface)

8 CLIs in `scripts/` (Phase 3/5 收敛). `kunglao.py` is the unified entry point
composing script pure functions; the rest are focused entry points / thin wrappers:

| CLI | Role |
| --- | --- |
| `kunglao.py` | unified entry point — subcommands composing existing script functions (JSON + exit codes frozen) |
| `kunglao-init.py` | workspace 初始化 + 防二次初始化 |
| `kunglao-decide.py` | M1 DECIDE — convergence_check.decide + explore_gate + priority_ratio |
| `kunglao-verify.py` | M3 VERIFY entry (impl in `kunglao_verify.py`) |
| `kunglao-record.py` | M4 RECORD entry (impl in `kunglao_record.py`) |
| `kunglao-monitor.py` | M5 MONITOR — heartbeat + reconcile + stuck/health watch → TickOutput |
| `kunglao-digest.py` | digest mechanical generation (thin wrapper → digest_build.py) |
| `kunglao-eval.py` | eval harness CLI (thin wrapper → kunglao_eval.py) |
