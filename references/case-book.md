# Case book — real failure modes from prior sessions

Load this when you recognize a situation that matches one of these patterns.
SKILL.md names each case; this file carries the full story and the fix.

## Case 1 — Idling when slots are free

Round 6 had slots < 3 and 2 OPEN claims, but the agent was waiting for the
user to "give direction". The user left for 40 minutes. Don't do that. If
you have free slots and open claims, your default next action is to dispatch.

**Addresses M1** (被动傻等). v1.9 fix: the convergence loop (the every-turn
check prevents this — open claims + free slots → must dispatch).

## Case 2 — Calling analysis tools directly

Round 11 of one run, the orchestrator called `mcp__ghidra__decompile` itself
instead of dispatching a worker. The result: a fact file with a verb-prefix
that violated §1b maker-checker (the orchestrator stamped its own work). The
fix is structural: analysis MCPs return evidence that the orchestrator did NOT
gather. Delegate.

**Addresses M8** (机械执行). See SKILL.md "Tool-use boundary" guardrail + the
specialist-first dispatch policy (behavior #2).

## Case 3 — Re-issuing the same dispatch after it failed

A worker got frida-attach failure on host. The orchestrator sent the same
prompt 3 more times before giving up. The right response on the first failure
is to ask the worker for a `## backtrack` decision (continue / retry-different
/ escalate / redispatch), not to re-issue.

**Addresses M2** (放弃修环境) + **M7** (重复工作). v1.9 fix: behavior #1
self-recovery chain (L1 same-MCP-other-mode / L2 read setup.sh / L3 dispatch
env-fix worker) + failure-analysis gate (you must record WHY the method failed
before re-dispatch).

## Case 4 — Asking the user "should I dispatch W-8?"

After a task finished, the orchestrator asked the user for direction. The
default is to dispatch the next open claim. Asking the user interrupts their
flow. Save questions for genuinely unrecoverable situations (e.g. contradicting
CTI, or zero OPEN claims and an empty fact base).

**Addresses M1** (被动傻等). v1.9 fix: every-turn convergence check tells you
the answer without asking.

## Case 5 — Stale plan vs reality

The user said "the plan and the actual state don't match". Plan files
(global_plan.txt, claim_deps.yaml) get stale when you re-plan, decompose,
or abandon claims. After every such change, run `scripts/plan_drift_detector.py`
and resolve the 5 drift types it reports.

**Addresses M6** (状态漂移). v1.9 fix: convergence_check.py surface-level
check of open/blocked claims per turn; health check detects flatline.
