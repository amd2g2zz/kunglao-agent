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

### Requirement: Launch-stash path components are single safe tokens

The claim and action_type formatted into launch-stash FILENAMES SHALL
be validated at both the read boundary (`pending_step` skips such a
stash — never pending, never consumed, never guessed) and the sink
(`_launch_path` refuses the shape for every caller — `record_launch`
and `append_transition` return None with ONE fail-open warn). A
worker-writable stash doc carrying `/` or `..` in either field SHALL
never resolve outside `runs/`, never unlink an arbitrary file, and
never bank a transition.

#### Scenario: a traversal claim is never consumed

- **WHEN** a stash doc whose claim is `x/../../victim-important` sits in
  runs/ (with a planted intermediate directory) and a settle fires
- **THEN** pending_step skips it, append_transition and record_launch
  refuse with ONE warn each, no transition row banks, and the victim
  file outside runs/ still exists

### Requirement: A rejected dispatch cancels the step it opened

`cancel_step_open` SHALL consume the untyped launch stash a rejected
attempt opened at the approval point and roll its `dispatch_count` bump
back (floor 0), wired into the dispatch-gate rc=2 undo path beside the
anchor undo and claim reopen. The barrier SHALL lift immediately (never
ride out the stale TTL on a never-dispatched attempt); typed sibling
stashes (verify / redteam / prediction-settle) and 1-F3 foreign
envelopes SHALL be left intact. The face SHALL be idempotent and
fail-open.

#### Scenario: approve then REJECT leaves no frozen barrier

- **WHEN** worker_budget approves (stash + dispatch_count accrue) and
  dispatch_gate then rejects (rc=2)
- **THEN** the undo consumes the stash, the dispatch_count returns to
  its pre-attempt value, the barrier admits the next dispatch at once,
  and a second cancel is a no-op

#### Scenario: a foreign envelope survives the cancel

- **WHEN** a status-bearing foreign doc is parked at the claim's stash
  path and cancel_step_open runs
- **THEN** the doc is left intact and the face reports False
