# Proposal: fix-239-plan-first-ownership — plan-first stops gating the FIRST dispatch

## Why

Issue #239 (regression of #7, live field evidence): the plan-first gate
(`hooks/worker_budget_gates.check_worker_plan`, wired as the `plan` pre_check
gate) gates the dispatch itself — a claim dispatch is REJECTED until
`runs/plan-C<NN>*.md` exists or the dispatch prompt references one. That
inverts plan ownership: the cheapest way for the orchestrator to unblock its
own dispatch is to ghostwrite the plan ("orchestrator-ghostwritten plan").
Dispatch carries intent, not a plan; planning is the worker's first act of
execution.

Owner ruling (settled, issue #239):

> "Dispatch carries intent, not a plan; planning is the worker's first act of
> execution."

## What Changes

- `hooks/worker_budget_gates.check_worker_plan` — CONTRACT CHANGE:
  - the FIRST dispatch of a claim (no prior approved dispatch in the claim's
    approval-point anchor log `runs/.dispatch-anchor-<KEY>.jsonl`) passes
    WITHOUT any pre-existing plan; the gate stops inspecting plan files on
    the first dispatch entirely (an orchestrator-ghostwritten plan is
    irrelevant to a first dispatch — it neither satisfies nor is required);
  - a RE-dispatch (>=1 prior approved dispatch for the claim) requires the
    plan reference: the on-disk plan (content + worker-session provenance
    via the existing #57 gate 3 `plan_author_violation` dispatch-anchor
    linkage) OR the plan path in the dispatch prompt (reserved for
    re-dispatch continuity);
  - first-dispatch vs re-dispatch is decided ONLY from the approval-point
    anchor log (what `stamp_dispatch_anchor` wrote for PRIOR dispatches) —
    the current dispatch's own KUNGLAO_DISPATCH_CONTEXT / context-file nonce
    never counts as a prior dispatch.
- `hooks/worker_budget_sinks.REJECT_FIXES['plan']` — repair text re-worded to
  the new contract (first dispatch: let the worker plan; re-dispatch:
  reference the worker-authored plan).
- `agents/kunglao-worker.md` golden rule #3 — the worker's first sanctioned
  write is its own plan (with the `dispatch-anchor:` provenance line);
  documented contract change.
- Tests re-pinned to the new contract (`tests/test_worker_budget.py`,
  `tests/test_framework_rigidity_57.py`) + new RED-first coverage in
  `tests/test_plan_first_ownership_239.py`.

## Capability Intent

Plan-first keeps its teeth where they belong: a claim cannot be EXECUTED
beyond its planning round without a worker-owned plan (provenance via the
per-dispatch anchor, mirroring #237 D3 maker != checker), while the first
dispatch can no longer be ghostwritten into "compliance" — there is nothing
left to satisfy at dispatch time.

## Out of Scope

- Umbrella issue #7 stays open (not reference-closed by this change).
- The B1o drift gate (#237 parallel branch) is untouched.
- No change to `plan_author_violation` evidence paths A/B (#57 machinery).
- No new write-side gate (the "worker's first sanctioned write is its own
  plan" duty is enforced by contract + the re-dispatch gate, not a new hook).
