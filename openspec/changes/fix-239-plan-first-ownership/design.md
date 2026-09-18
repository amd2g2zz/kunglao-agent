# Design — fix-239-plan-first-ownership

## Decision

`check_worker_plan(paths, cid, prompt)` keeps its signature and its wiring
point (`('plan', check_worker_plan(paths, cid, prompt))` in
`hooks/worker_budget_sinks.pre_check`). The gate's SEMANTICS flip:

```
prior = rows in runs/.dispatch-anchor-<KEY>.jsonl   # approval-point log ONLY
if not prior:            # FIRST dispatch of the claim
    PASS — "dispatch carries intent, not a plan; the worker's first
            sanctioned write is its own plan"
else:                    # RE-dispatch (beyond the planning round)
    on-disk plan (empty-shell check + plan_author_violation provenance)
    OR prompt plan-path reference (re-dispatch continuity)
    else REJECT
```

## Why the approval-point log is the only prior-dispatch source

`_dispatch_anchor_issued` merges three sources: the anchor log, the #527
context file (`runs/dispatch-context-<KEY>.json`), and the prompt's own
`KUNGLAO_DISPATCH_CONTEXT` block. The latter two are composed by the
orchestrator BEFORE the Agent tool call fires — they carry the CURRENT
dispatch's nonce. Using them for first-dispatch detection would classify
every dispatch (including the first) as a re-dispatch and re-create the
dispatch-time gate this change removes. Only the anchor log is written at
APPROVAL of PRIOR dispatches (`stamp_dispatch_anchor` runs after the gate
battery passes, #754 lifecycle-silence), so "log has rows" == "this claim was
dispatched and approved before".

## Provenance (plan ownership) — reused, not reinvented

#57 gate 3 (`plan_author_violation`) already implements maker != checker for
plans: the on-disk plan must cite an issued dispatch anchor (path A) or carry
a `dispatch-anchor:` line with an mtime after the first issued dispatch
(path B). On a re-dispatch the anchor log exists, so the author gate is
armed exactly when the plan is required. An orchestrator-ghostwritten plan
(written before the first dispatch, citing nothing) fails both paths — and
under the new contract it no longer buys the first dispatch anything, which
removes the incentive the field evidence exposed (#239).

## Contract change (documented)

- OLD: every claim dispatch requires `runs/plan-C<NN>*.md` or an in-prompt
  plan reference (dispatch-time enforcement; first dispatch included).
- NEW: first dispatch of a claim is plan-free (planning is the worker's first
  act of execution); re-dispatch beyond the planning round requires the plan
  reference; the in-prompt `--plan` reference is reserved for re-dispatch
  continuity.

## Fail-open posture

Unchanged: no workspace -> pass; unreadable plan -> pass with honest note;
no anchor log on a legacy workspace -> treated as first dispatch (same
"not armed -> legacy posture" discipline as #57).

## Alternatives rejected

- Gating the worker's Write face (a write_guard-style "first worker-surface
  write must be the plan"): adds a new hook face outside the confined
  plan-first pathway; the contract + re-dispatch gate achieve the ruling's
  effect without a new enforcement surface.
- Requiring the re-dispatch prompt reference to point at an EXISTING file:
  redesign beyond the ruling; the continuity leg keeps its timing relaxation.
