# Design

## Context

The policy core is pure by contract (PURE_POLICY__HOST_SPLIT): helpers
take `now`, clamps sit at named bounds, and the row stamps
(`rollout-timer/1`, `rollout-budget/1`) are already registered native
telemetry. What was missing is the data movement: who calls arm when a
dispatch starts, who calls cancel + learn when a rollout finishes, and
who executes the one-shot cron wake. The dispatch lifecycle already has
ONE semantic owner (claims_store's journalled transaction) and the
round closure already has ONE event (SubagentStop = the round closure),
so the wiring needs no new lifecycle — only faces on the existing ones.

## Goals / Non-Goals

Goals:
- One arm per committed dispatch; one cancel + learn per finished
  rollout; one deterministic executor for the deadline wake.
- Keep the host dumb: it resolves identities (dispatch ledger id,
  method family, difficulty tier), moves data, and lets the policy
  table decide — it never re-implements the outcome math.
- Fail-open telemetry at every seam (double cage in the hook): a timer
  failure is one canonical warn and never disturbs the dispatch
  verdict, the settlement path, or the subagent stop.
- Deadline censoring at the host level: a fired timer's round close is
  cancel-only — deadline stops never enter strategic learning.

Non-Goals:
- The Stop-hook boundary (timer-not-due → allow / due → block) —
  a follow-up for this change, not this slice.
- The event-driven wake path (FileChanged + asyncRewake,
  events.jsonl) — the next slice (needs this one).
- Removing the heartbeat/`*/5` cron stack — the removal matrix slice
  owns it with the consumer audit; the skill text keeps both contracts
  until then.

## Decisions

### D1. The arm rides the commit, not the intent

`begin_dispatch` opens a journalled intent that can abort or recover
before the register flip; only `commit_dispatch` marks a dispatch that
actually started. Arming at commit means a recovered/aborted intent
never leaves a phantom timer. The rollout identity is the dispatch
journal id (the dispatch-ledger id minted at the approval point) —
the same key every downstream row foreign-keys, so timer rows,
settlement attribution and the q-cell bank join without an alias.
The guarantee extends through the post-commit recovery window: when
`recover` inverts a COMMITTED journal (owner died before
`confirm_dispatch`), it cancels the armed timer through the host's
cancel-only discard face — the dispatch never happened from the
register's view, so no timer (and no outcome) may survive it.

### D2. The wake contract publishes to a per-rollout map file

The orchestrator's CronCreate/CronDelete faces run in the agent
session, the arm runs in a hook process — the contract crosses that
boundary on disk. `runs/rollout-timer-wake.json` follows the house
state-file pattern (policy-state.json, distill-trigger.json) but is a
MAP keyed by rollout_id (`{rollout_id: contract}`), not a single slot:
concurrently-armed rollouts publish side by side, a deadline stop
overwrites only its own key, and a round close (or a recovery discard)
pops only its own key — no cross-rollout clobber is possible within
one process (the journal serializes arm/discard; the load-modify-save
is not serialized across processes — an interleaving external cron
wake drops or resurrects at most one advisory entry, the ledger stays
durable, and a stale fire refuses), and the last entry out unlinks
the file. The durable truth is the telemetry ledger; losing the file
degrades the publish face, not the state machine.

### D3. The host classifies, the table decides

The round close maps the settle receipt onto the bounded table's own
words: completed within the early band → `early`, completed within
budget → `on_time`, a failed worker or a completion past its budget →
`aborted` (the honest no-update word), and the wake path learns
`timeout` after a fired deadline. The host never invents factors —
`next_coefficient`'s predicate refusals remain the audit trail for
inconsistent predicates. The round close re-checks the fired state
immediately before its learn: a cron wake flipping the timer inside
the decide-then-learn window bails to the censor path (cancel only,
no learn), and the policy table's fired-deadline predicates back the
refusal.

### D3b. The median feeds on OBSERVED durations only (policy-core touch)

The wake's timeout learn records actual_min = the budget — the true
duration is unknown (the rollout never finished), so timeout rows are
right-censored data. The policy core's median feed therefore counts
OBSERVED completions only (`DURATION_OUTCOMES` = early/on_time in
`rlvr/rollout_timer.py`): a timeout-heavy history can no longer drag
the family median toward the budget (the pegged-coefficient fixed
point EXP-B1's P4 exists to catch). The coefficient table is
UNTOUCHED — timeout keeps its ×1.25 update, and the bucket floor
still counts timeouts as informative samples (`SAMPLE_OUTCOMES`).
This is the one deliberate touch to the policy core, justified by the
review's censoring-bias analysis and pinned by test.

### D4. Deadline censoring is enforced at the round close

A folded timer with `fired_ts` is censored: the round close cancels
(post-settlement cleanup) and skips learn entirely. The exclusion
markers ride the rows themselves (`stop_reason: deadline`,
`excluded_from_strategy_learning: true`), so any downstream strategic
feed can filter mechanically — pinned by the experiment and the tests.

### D5. The wake CLI is one deterministic command

The cron wake must not improvise five LLM-driven bookkeeping steps.
`scripts/rollout_timer_wake.py --wake <rollout_id>` performs fire +
stop record + cancel + learn in one process, prints the receipt JSON
with the graceful-stop contract, and exits 3 on a refused wake (not
due / canceled / unknown). The wrap-up TURN still does the judgment
work (persist evidence, settle) per the published prompt — the command
does the mechanical closure.

### D6. Difficulty family reads the same feed the gates read

`difficulty_thresholds.thresholds_for_workspace` (evidence/
difficulty.json → task_spec `difficulty:` → fail-closed `hard`) — the
same resolution the promotion gates use, so the timer's families can
never disagree with the gate's. Kind = the declared method family
(fallback `claim`): comparable rollouts are same-approach,
same-difficulty work.

## Risks / Trade-offs

- `commit_dispatch` gains one fail-open face — the transaction's
  failure semantics are unchanged (the arm runs AFTER the committed
  provenance row; any timer trouble warns and returns), and the
  post-commit recovery window cancels the armed timer cancel-only.
- Re-learning a fired rollout is impossible (one learn per rollout,
  divergent repeats refused) — the wake path is the only legitimate
  learner for a deadline stop, and the round close's censor + the
  immediate fired re-check keep the second call from ever landing.

## Migration Plan

No migration: the timer rows start at zero on existing workspaces; a
dispatch committed before this change simply has no timer (the round
close resolves the dispatch id, finds no timer, and stays silent).

## Open Questions

- The Stop-hook boundary (block-at-stop until the wrap-up completes)
  is deliberately deferred; the wrap-up prompt contract already pins
  the behavior.
- The bucket split (per-(kind, difficulty) coefficients once a bucket
  reaches its sample floor) stays policy-gated in `bucket_ready`; the
  activation card is future work.
