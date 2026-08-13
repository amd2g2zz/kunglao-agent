> **ARCHIVED (2026-08-13, #263)**: historical, v1.8.1 snapshot. Moved from references/ to references/archive/. Retained for design-traceability; not referenced by any active code.

**Heuristic**: this is a SURVEY of v1.10-a/b design ideas - **PRE-IMPLEMENTATION research**. Do NOT act on these ideas; use only as reference for v1.10 design discussions. Most of the cited mechanisms are not yet built into kunglao-agent (ElHPlan action chains, Task-Decoupled planning, LangGraph PostgresSaver-style checkpoints).
# Long-Horizon Agent Architecture Reference Survey (2026-07-28)

> **Authority**: archived research for **kunglao-agent v1.10-α** design.
> **Status**: pre-implementation reference. NOT yet integrated into kunglao-agent.
> **Becomes actionable after**: v1.9 ships + at least 1 sample fully converged under v1.9.
> **Survey cut**: 2026-07-28 (15+ websearch rounds, 5 references deep-dived).

---

## Why this file exists

kunglao-agent v1.8.1 is a **single-session reactive orchestrator** with no
backtrack, no replan, no checkpoint, no proactive search. The user asks:
"can kunglao-agent complete long-horizon RE tasks?" — answer (v1.8.1): **no**.
This file catalogs the reference architectures that long-horizon agent
research has produced, mapped to the concrete failure modes kunglao-agent has,
mapped to the specific kunglao-agent files / hooks / state that would need to
change.

When v1.10-α starts, the design doc should cite this file. Every concrete
change below has been sanity-checked against the cited paper.

---

## §1. Five Reference Architectures (one row per reference)

| # | Reference | arXiv / URL | Core innovation | kunglao-agent failure mode it addresses |
|---|---|---|---|---|
| 1 | **Plan-and-Act** | [arXiv 2503.09572](https://doi.org/10.48550/arXiv.2503.09572) | PLANNER + EXECUTOR + per-step garbage collection + dynamic replan | monolithic orchestrator; no GC; no replan |
| 2 | **ELHPlan** | [arXiv 2509.24230](https://arxiv.org/abs/2509.24230) | Action Chains = action sequences **explicitly bound to sub-goal intentions** | claim_deps has no intent binding; no expected-evidence contract |
| 3 | **Task-Decoupled Planning** | [arXiv 2601.07577](https://arxiv.org/abs/2601.07577) | split **task layer** (intent) from **dependency layer** (preconditions) | global_plan.yaml currently entangled; replan scope = whole iteration |
| 4 | **LangGraph Checkpoint** | [official docs](https://langchain-ai.github.io/langgraph/reference/checkpoints/) | Pregel super-step + PostgresSaver + thread_id primary key + parent_checkpoint_id chain | no checkpoint at all; 8-file cold-start is manual |
| 5 | **Anthropic Effective Harnesses** | [tool.lu mirror](https://tool.lu/en_US/article/7wa/preview) + [cwc-long-running-agents repo](https://github.com/anthropics/cwc-long-running-agents) | Initializer Agent + Coding Agent + feature list + progress.json + per-session git commit | no per-session clean state; no progress.json; no git checkpoint |

---

## §2. Plan-and-Act — details

**When**: 2025-03
**Architecture** (algorithmic, from CSDN 解读):

```
loop:
  plan = PLANNER(goal, current_state, history)
  step = plan.pop_next()
  result = EXECUTOR(step, environment)
  cleanup(step.intermediate_data)   # garbage collection
  history.append(result)
  if replan_triggered(result):
      plan = PLANNER(goal, current_state, history)
  if plan.empty:
      return aggregate_results(history)
```

**Two roles**:
- PLANNER (LLM): decomposes goal into structured steps; supports dynamic replan
- EXECUTOR (LLM agent): runs each step; calls tools; makes environment changes

**Garbage collection** (key insight): EXECUTOR deletes unnecessary data
before executing next action. This is the **single biggest** reason Plan-and-Act
beats monolithic ReAct on long-horizon tasks.

**kunglao-agent v1.10-α target changes**:
1. `SKILL.md` §3 — split "you are the orchestrator" into dispatcher + executor
   sub-roles (still orchestrator-coordinated, but each consumes a constrained
   context window).
2. `hooks/worker_budget.py` — extend `pre_check` with a `cleanup_indirect_artifacts`
   step that deletes `analysis_artifacts/<run_id>/` and `decomp/<run_id>/` after
   the worker returns + verifies.
3. `references/loop-semantics.md` (new) — document the PLANNER (mono, owns
   plan) → EXECUTOR (per-dispatch, owns tool calls) split.

**Risk**: double-loop vs single-loop behavior change. Mitigation: keep external
contract (output = fact base; convergence = primary questions answered) unchanged.

---

## §3. ELHPlan — details

**When**: 2025-09
**Architecture**: cyclical 4-stage process

1. **Constructing** intention-bound action sequences
2. **Proactively validating** for conflicts and feasibility
3. **Refining** issues in invalidated actions
4. **Executing** validated actions

**Core innovation**: Action Chains are **action sequences explicitly bound to
sub-goal intentions**. Each action must be traceable to the intent that
produced it.

**Trade-off addressed**: open-loop compilers (sound but inflexible) vs
iterative replanners (adaptable but cost O(n²)). ELHPlan balances by
keeping action chains short enough to fit a single context window.

**kunglao-agent v1.10-β target changes**:
1. `claim_deps.yaml` schema — add per-claim field
   `dispatch_intent: "<single-sentence intent>"` and
   `evidence_expected: <list of fact types or claim IDs>`.
2. Worker prompt template — accept `dispatch_intent`; require worker return
   to declare which `evidence_expected` items were fulfilled.
3. `references/verify-static-vs-dynamic.md` — extend with intent-vs-result
   comparison: if 0 of `evidence_expected` fulfilled, the dispatch is invalid
   even if the worker returned success.

**Risk**: required schema change breaks existing claim_deps.yaml. Mitigation:
additive fields; old claims without `dispatch_intent` get `dispatch_intent: null`
(augmented by orchestrator on next cold-start).

---

## §4. Task-Decoupled Planning (关键发现)

**When**: 2026-01
**Architecture**: split the plan into two independent layers

- **Task Layer**: high-level intent (e.g., "analyze family attribution")
- **Dependency Layer**: low-level dependency graph (e.g., "must first get
  binary fingerprint") — owned by `claim_deps.yaml`

**Why decoupling matters**: when current LLM planning fails, the error
propagates through both layers. Decoupling allows replanning only the
failed layer.

**kunglao-agent v1.10-β target changes**:
1. `global_plan.yaml` — split into `global_plan_tasks.yaml` +
   `global_plan_deps.yaml`. The `tasks` file lists claim IDs grouped by
   primary question; the `deps` file lists claim ID → required-evidence IDs.
2. `references/cold-start-contract.md` §8 — update to read 9 files instead
   of 8.
3. Orchestrator MONITOR — when a claim transitions OPEN → REFUTED, only
   the dep layer is re-evaluated; the task layer is unchanged.

**Risk**: 8 → 9 file reads; cold-start gets ~15% slower. Mitigation: add
digest layer (LangGraph-style; see §5).

---

## §5. LangGraph Checkpoint — implementation details

**Production schema** (PostgresSaver):

```sql
CREATE TABLE checkpoints (
  thread_id TEXT,
  checkpoint_ns TEXT,
  checkpoint_id TEXT,
  parent_checkpoint_id TEXT,
  type TEXT,
  blob BYTEA,
  metadata JSONB,
  PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);
```

**Key APIs**:
- `graph.getState(config)` — retrieves latest checkpoint for a thread
- `checkpointer.list(config)` — full timeline
- `graph.getStateHistory(config)` — full history with metadata
- resume via `graph.invoke(input, config={configurable: {thread_id: "..."}})`

**Linked chain** via `parent_checkpoint_id` → time-travel debugging.

**kunglao-agent v1.10-α target changes**:
1. `.checkpoint/state_<iter>.json` — directory under workspace; one file per
   MONITOR-end. Schema:
   ```yaml
   checkpoint_id: iter_5_step_3
   parent_checkpoint_id: iter_5_step_2
   state_snapshot:
     claim_register: <shallow ref, not full YAML>
     analysis_state: <shallow ref>
     facts_index: <shallow ref>
   metadata:
     iter: 5
     phase: MONITOR
     budget_used: 0
   ```
2. Storage: JSON file (not Postgres) — kunglao-agent is workspace-isolated, not
   multi-tenant. Shallow refs avoid 100MB+ snapshots.
3. `references/cold-start-contract.md` — extend with `.checkpoint/` read;
   if `state_<iter>.json` exists, ask user "resume from iter N?".

**Production considerations** (from LangGraph):
- TTL / cleanup: implement orbit-on-iter-N+10 (keep last 10 checkpoints).
- Async preferred: not applicable (synchronous orchestrator).
- Backup: git commit `.checkpoint/` every session end.

---

## §6. Anthropic Effective Harnesses — practical mechanics

**When**: 2025-11
**Repo**: [anthropics/cwc-long-running-agents](https://github.com/anthropics/cwc-long-running-agents)

**Two agents**:
- **Initializer Agent**: runs once, doesn't write code; breaks user requirements
  into a complete **feature list** (JSON)
- **Coding Agent**: edits incrementally, commits clean Git records, writes
  **progress files** after each session

**Three failure modes solved**:
1. **One-shotting**: agents try too much, exhaust context mid-task
2. **State loss on failure**: network timeout / restart wipes in-memory progress
3. **Context degradation**: beyond ~40% of 168K window, agents enter "Dumb Zone"

**progress.json schema** (from CSDN 解读):

```json
{
  "features": [
    {"id": "F001", "status": "done", "evidence": "..."},
    {"id": "F002", "status": "in_progress", "blocked_by": null},
    {"id": "F003", "status": "blocked", "blocker": "..."}
  ],
  "progress_notes": "...",
  "session_marker": "session-12"
}
```

**kunglao-agent v1.10-α target changes**:
1. `progress.json` schema — adapt to claim-centric. Replace `features` with
   `claims` (mapping to claim-register claim IDs). Status values:
   `done` / `in_progress` / `blocked` / `ctx_degraded`.
2. `references/cold-start-contract.md` — read `progress.json` before 8 files.
3. `hooks/worker_budget.py` — add `check_progress_json` (warn if not updated
   in last N iterations).
4. **Git checkpoint**: every MONITOR end → `git add -A && git commit -m "iter N: state checkpoint"`.
   Hook in `worker_budget.py` post_check.

**Risk**: orchestrator may not have write access to git repo. Mitigation: gate
behind "git available" check; if not, fall back to "write progress.json only".

---

## §7. v1.10 Roadmap (consolidated)

| Stage | LOC | Duration | What ships |
|---|---|---|---|
| **v1.9 ship** | ~300 | 2-3 weeks (POC1-3) | Coverage-matrix + dead-end prune (per review_round_1 review files) |
| **v1.10-α** | ~200 | 4 weeks | Plan-and-Act split + PostgresSaver-style .checkpoint/ + Anthropic progress.json + git checkpoint hook |
| **v1.10-β** | ~200 | 4 weeks | ELHPlan Action Chain (intent binding) + Task-Decoupled global_plan + dep-layer-only replan |
| **v1.10 ship** | ~400 | 8 weeks total | every kunglao-agent failure mode closed by a cited reference |

**Hard preconditions for v1.10-α start**:
1. v1.9 fully shipped (POC1-3 done, at least 1 sample converged)
2. v1.9 reviewed: no regression in v1.8.1 invariants (maker-checker, WAL,
   dual-hook, 8-file cold-start, 5 hard prohibitions including #5 VM-only)

**Acceptance gates for v1.10-α**:
- Each new mechanism has a POC (≈30-line Python script) that exercises it
  against the current workspace before commit.
- A short "delta vs v1.9" baseline: x the same workspace before/after; loss
  of any v1.8.1 invariant = abort.
- The Dual-hook (Pre+Post on Agent) output for §2-§6 changes is verified
  by replaying the same hypothetic dispatches.

**Acceptance gates for v1.10-β**:
- A 5-KB synthetic sample is run through full v1.10-β loop and converges
  in ≤3 iterations (vs ≥5 for v1.9).
- `.checkpoint/time-travel` test: rewind to iter 3, replay forward, verify
  identical claim-register state at iter 4.

---

## §8. What NOT to do (anti-patterns)

| Anti-pattern | Why it fails | Avoidance |
|---|---|---|
| Replacing all 8 files with a single SQLite DB | Breaks git-versionable fact base; breaks `git-checkpoint.sh` precedent | Keep YAML files; add `.checkpoint/` alongside |
| Adding a planning LLM call every iteration | Doubles session cost; v1.9 evidence is current budget is already tight | PLANNER only fires on (a) verification, (b) refutation, (c) task_spec update |
| Replacing claim_deps.yaml with a graph DB | Vendor lock-in; breaks existing cold-start contract | Add `dispatch_intent` field; don't replace schema |
| Time-travel debugging in production | Adds complexity; rarely used | Only enable `getStateHistory` in dev mode |
| Replan on every worker failure | Cascades failures; defeats maker-checker | Replan only on (a) verified PROVEN-FULL, (b) PROVEN-REFUTED via §9 rule 4(b), (c) task_spec update |

---

## §9. v1.10 ship-go-no-go criteria (consolidated)

**GO** if:
- ≥1 sample fully converged under v1.10 same-or-faster than v1.9
- v1.8.1 5 hard prohibitions + maker-checker + WAL + dual-hook + 8-file cold-start all preserved
- ≥80% of v1.9 audit_slots / coverage_matrix behavior preserved

**NO-GO** if:
- Any v1.8.1 invariant broken
- Session cost >2× v1.9 for same convergence
- Time-travel debugging requires schema migration breaking existing workspaces

---

## §10. When to cite this file

- v1.10 design doc — must cite at least one section per change
- v1.10 review (any reviewer) — must verify cited section matches actual change
- Skill maintenance — when adding new mechanism, add row to §1 table

---

## §11. Provenance & session cost

- **Survey performed**: 2026-07-28, in-session (session cost ~$300 at survey end)
- **Survey rounds**: 15+ websearch + 4 deep-dive
- **Survey sponsors**: user "需要调研更多资料" + "继续调研"
- **POC evidence**: hand-coded coverage_matrix.yaml on `2995ffb7` workspace
  signaled v1.9 is actionable; v1.10 is next
- **Storage**: this file is single-source-of-truth; do not duplicate in
  DESIGN.md, SKILL.md, or notes/

---

## Sources

- [Plan-and-Act: Improving Planning of Agents for Long-Horizon Tasks (arXiv 2503.09572)](https://doi.org/10.48550/arXiv.2503.09572)
- [ELHPlan: Efficient Long-Horizon Task Planning for Multi-Agent Collaboration (arXiv 2509.24230)](https://arxiv.org/abs/2509.24230)
- [Beyond Entangled Planning: Task-Decoupled Planning for Long-Horizon Agents (arXiv 2601.07577)](https://arxiv.org/abs/2601.07577)
- [LangGraph PostgresSaver Reference](https://langchain-ai.github.io/langgraph/reference/checkpoints/)
- [LangGraph 持久化深度解析 (CSDN)](https://blog.csdn.net/m0_59235245/article/details/161024839)
- [Anthropic cwc-long-running-agents GitHub](https://github.com/anthropics/cwc-long-running-agents)
- [Anthropic Effective Harnesses 原文翻译 (CSDN)](https://blog.csdn.net/Jas000/article/details/156465105)
- [Deer-Flow Deep Dive: Managing Long-Running Autonomous Tasks](https://www.sitepoint.com/deerflow-deep-dive-managing-longrunning-autonomous-tasks/)
- [Harness Engineering 2026 综述 (CSDN)](https://blog.csdn.net/qq_31142761/article/details/159823606)
