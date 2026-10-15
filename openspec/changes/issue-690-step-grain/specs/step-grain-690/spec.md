# step-grain-690 delta — issue-690-step-grain

## ADDED Requirements

### Requirement: SubagentStop settles the pending step

`settle_step` (hosted by the round-closure SubagentStop hook) SHALL
close the pending step: map the claim from the dispatch-launch stash,
aggregate the session's step-record/1 tool-call rows into ONE
step-record/2 row carrying `claim_ref` and a deterministic `step_id`,
and append the transition via `incremental_reward.append_transition`
(the production caller). Settlement SHALL run before the compose face
so decision faces read post-settlement state. With no pending step the
settle SHALL write nothing and never warn. Every error face SHALL be
fail-open: ONE warn, never a raise into the subagent's stop path.

#### Scenario: a subagent completion triggers settlement

- **WHEN** a dispatch launch stash exists and the SubagentStop hook fires
- **THEN** runs/transitions.jsonl gains the claim's transition row, the
  launch stash is consumed, and the step ledger gains one
  step-record/2 row whose claim_ref is the stash's claim and whose
  tool_calls counts the session's tool-call rows

#### Scenario: a non-worker subagent stop is silent

- **WHEN** SubagentStop fires with no pending step
- **THEN** no transition row, no step-record/2 row, and no warn land

### Requirement: No dispatch while a prior step is unsettled

The dispatch battery SHALL reject a new dispatch while a prior step is
unsettled (settle -> update -> decide). A pending step older than the
step-settle TTL (the SubagentStop never fired) SHALL be admitted with
ONE warn (fail-open — a crash must not deadlock the loop), as SHALL any
unreadable barrier state.

#### Scenario: the barrier blocks then lifts on settle

- **WHEN** a launch stash is pending and a new dispatch is attempted
- **THEN** the gate rejects naming the pending claim; after settle_step
  consumes the stash the same gate admits

#### Scenario: a stale pending step admits fail-open

- **WHEN** the pending stash's ts is older than the TTL
- **THEN** the gate admits with a warn naming the stale claim

### Requirement: Steps aggregate by session with deterministic step ids

`aggregate_session_steps` SHALL roll a session's step-record/1 rows into
one aggregate (tool_calls, call_id hashes, first/last ts, summed
durations) without leaking other sessions' rows, and `step_id_for` SHALL
be a deterministic function of (session_id, ordinal) — equal inputs
yield equal ids, different ordinals or sessions never collide.

#### Scenario: one session aggregates, others stay out

- **WHEN** three tool-call rows exist for sess-a and two for sess-b
- **THEN** sess-a's aggregate counts exactly its three call_ids and the
  step ids for (sess-a, 0), (sess-a, 1), (sess-b, 0) are pairwise distinct

### Requirement: branch_budget is a hard constraint with attributed waste

The dispatch envelope's branch_budget SHALL be enforced: a wall_s
overrun at settle lands one `attributed-waste/1` row attributing
(actual − budget) seconds to the claim and step; a consumed retries
budget REJECTs the claim's next dispatch. `dispatch_count` SHALL accrue
independently of `promotion_attempts` at every approved dispatch and
SHALL surface in the rank feed when non-zero (absent when zero — legacy
feeds unchanged). Malformed or absent budget dims SHALL be
unconstrained (fail-open).

#### Scenario: a wall_s overrun lands in attributed-waste

- **WHEN** a step settles 900s after launch with branch_budget.wall_s=600
- **THEN** runs/attributed-waste.jsonl carries a wall_s_overrun row with
  budget_s=600, actual_s≈900, waste_s≈300, claim_ref and step_id set —
  and a within-budget settle writes no row

#### Scenario: the retries budget blocks the next dispatch

- **WHEN** dispatch_count reaches branch_budget.retries for the claim
- **THEN** the battery rejects the next dispatch naming the exhausted
  budget; with no budget the dispatch is unconstrained and the register
  shows dispatch_count accrued with promotion_attempts untouched
