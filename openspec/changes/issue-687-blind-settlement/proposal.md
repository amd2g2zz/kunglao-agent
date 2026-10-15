# issue-687-blind-settlement — the blind settler

## Why

Settlement is done by the orchestrator over its own workers' output —
no isolation between producer and grader. Credit is the reward: whoever
writes it can shape it, so any path where the producer (or the
orchestrator that dispatched it) can move its own credit is a
reward-hacking surface, and the escrow/revoke calibration (#130) is
meaningless if the confirmation signal is not independent. The handbook's
BLIND verifier contract covered *verification of claims* but never
*settlement of credit*; `verdict-scorer` scores `evidence/verdict.json`
against `task_spec.primary_questions`, it does not settle steps.

## What Changes

1. **The blind settlement entry** — `scripts/rlvr/settlement_scorer.py`:
   - `settler_input` builds the input doc from a WHITELIST (raw step
     artifacts as path + sha256, the claim/question it targets, the
     settlement rules table as path + sha256). Producer narrative
     (`notes/`, `runs/worker-status-*`, `runs/verification-*`,
     `runs/*-verify-note.md`, fact conclusions, `evidence/verdict.json`)
     and the policy learning faces (`runs/method-family-log.jsonl`,
     `runs/q-cell-log.jsonl`) are refused at the door — the builder
     raises before any read, and a legal build opens exactly the listed
     artifacts (it never scans the workspace).
   - `check_blind_input` re-enforces schema + settler identity +
     the excluded-face scan at the SETTLEMENT, so a hand-built doc
     cannot smuggle what the builder refuses.
   - `settle_blind` reuses the deterministic stack unchanged:
     `scalar.validate_verdict_doc` (citation wall → rail clamp → oracle
     lock → anti-surrender floor) then
     `scalar.apply_trajectory_settlement` (fail-closed write; duplicate
     re-application is refused by the ledger's core-minus-ts dedupe, so
     the ledger file stays byte-identical). One additive seam:
     `apply_trajectory_settlement(extra_resolvable=...)` (default empty)
     lets the input doc's own artifact paths vouch as citable ids — a
     verdict cites the bytes it actually saw.
   - `record_settler_cost` / `settle_blind(cost_tokens=, cost_seconds=)`
     books the settler's OWN run cost through
     `incremental_reward.append_transition(action_type="settle")`, so
     the grader's tokens/seconds enter `cost_t` (r_incr = ALPHA·ΔΦ −
     LAMBDA·cost_t) exactly like any producer act's. The launch stash
     is the billing guard: no stash → no row; the first close consumes
     it, so a re-run cannot double-bill. Cost without a claim is a
     loud refusal, never a silent drop.
2. **The settler agent** — `agents/kunglao-settler.md`: the settlement
   subagent under the extended BLIND contract (input doc only, never
   producer context; identity on every verdict; deterministic ruling;
   never writes the ledger — the mechanical entry does). Verifier
   identity follows the dual_gate discipline: no non-empty identity,
   no settlement.
3. **Mechanical blindness for the act** — `hooks/rt_read_barrier.py`
   gains the settler identity family (`SETTLER_AGENT_MARKERS`) riding
   the SAME deny faces as the red-team (Face A agent_type + Face B
   armed dispatch envelope), and both families now deny the two policy
   learning faces (`runs/method-family-log.jsonl`,
   `runs/q-cell-log.jsonl`) across the Read / Glob-pattern / Bash-token
   faces — a grader that knows which arm produced a step can shape
   credit per arm.
4. **Acceptance pins** — `tests/test_blind_settlement_687.py` (the four
   card tests + identity gate) and settler-family pins added to
   `tests/test_rt_read_barrier_652.py`.

## Out of scope (recorded seams)

- **Production wiring / timing**: who dispatches the settler at the
  step boundary and feeds `settle_blind` its cost arguments rides the
  step-grain card; nothing in production writes an
  `action_type=settle` launch stash yet (zero live cost rows by
  construction).
- **The settlement row's round-credit trio** (`credited`, `demoted`,
  `untraced`) stays the existing `scalar.settle_round_credit` face —
  the trajectory settlement writes `reward`/`band`/`rule_id`/
  `evidence_refs`; folding both faces into one settler-emitted row is a
  wiring-card decision, not this card's.
- **verdict-scorer re-role**: the PQ-coverage scoring face is untouched
  (the issue allows keeping it separate); the settler is a new agent,
  not a rename.
- **Verifier-remediation classification**: `kunglao-settler` is NOT
  added to `blind_gate.VERIFIER_AGENT_MARKERS` /
  `lib_kunglao.VERIFIER_REMEDIATION_AGENTS` — those classify
  remediation dispatches for PROVEN claims (a different contract); the
  settler marker only ever RESTRICTS reads inside the barrier.
