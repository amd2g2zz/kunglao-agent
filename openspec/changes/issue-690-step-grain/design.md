# design — issue-690-step-grain

## Grain decision

`step := one subagent completion (SubagentStop)`. The per-tool-call
step-record/1 rows (#670) remain the shadow substrate; the settlement
unit is their SESSION aggregate, written as one step-record/2 row.

## The three faces

### settle (rlvr/step_grain.settle_step, hosted by hooks/round_closure)

    pending stash ──claim_ref──▶ step-record/2 row (session aggregate)
    pending stash ──phi_before──▶ append_transition (Φ(s′) at settle)
    branch_budget.wall_s ──▶ attributed-waste/1 row on overrun

- The claim mapping is the dispatch-launch stash: the approval point
  (`worker_budget_sinks._open_step`) calls `record_launch` (which now
  carries `branch_budget` additively); SubagentStop has no claim id, so
  the OLDEST unsettled stash IS the step being settled (see barrier —
  at most one fresh pending step exists by construction).
- Ordering inside the closure kernel: settle runs BEFORE compose, so
  the strategy object and the RL digest always see post-settlement
  state (settle -> update -> decide).
- `step_id = sha256([session_id, ordinal])[:16]` — ordinal = count of
  already-settled steps for the session. Deterministic replay, no
  clock, no rng.
- Fail-open end to end: no pending step → silent None (SubagentStop
  also fires for non-worker subagents); any error → ONE warn, the stop
  path never disturbed.

### barrier (worker_budget_gates.check_step_settled, FIRST battery gate)

- Fresh unsettled stash → REJECT (zero dispatches against an open step).
- Pending older than `liveness_policy.STEP_SETTLE_TTL_MINUTES` (120) →
  admit + ONE warn: a crashed SubagentStop must not deadlock the loop;
  `sweep_orphan_launches` still catches the stash at end of run.
- Read error → admit (fail-open: a broken ledger never newly blocks).

### budget (branch_budget: the parsed field gets consumers)

- `retries`: `check_branch_budget` REJECTs when the claim's
  `dispatch_count >= retries`. `dispatch_count` accrues at the APPROVAL
  point (`bump_dispatch_count`, register field via ws_yaml) —
  INDEPENDENT of promotion_attempts (the settlement-side cap the issue
  measured pinned at 0).
- `wall_s`: priced at settle — actual wall (stash ts → settle ts) over
  budget lands one `attributed-waste/1` row (claim_ref, step_id, kind
  `wall_s_overrun`, budget/actual/waste seconds).
- Malformed/absent budget dims → unconstrained (v1 envelope back-fill
  via envelope_v2_defaults; fail-open on garbage).

## Recorded trade-offs

- Single-pending-step invariant: the barrier makes "oldest unsettled
  stash" an unambiguous claim mapping. Parallel fine-grained claims
  (issue proposal #4) will need a session→claim map; recorded as the
  next card, not built speculatively here.
- The dispatch-count counter is a REGISTER field (not a runs/ file) so
  the ranker needs no extra I/O — it already loads claim dicts.
- Stale-TTL admit is deliberately warn-loud: an operator watching the
  transcript sees the fail-open fire instead of discovering a silent
  deadlock.
