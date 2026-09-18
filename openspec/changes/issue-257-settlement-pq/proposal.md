# issue-257-settlement-pq — wire settlement to posteriors update_eliminate/update_evidence (ΔH goes live)

## Why

Issue #257: `scripts/posteriors.py` `update_eliminate`/`update_evidence` have
zero production callers; `oracle_runner.record_posteriors` updates the case
Bernoulli face only — `ledger.pqs` is never written, so the ΔH term priced at
`priority_ratio.py` LAMBDA_DH (`dh = pq_cat.entropy()`) is structurally ≡ 0 and
`entropy_face.frontier_entropy` always reports (None, None). The EXP-3 spike
(issue comment, authoritative) proved the bookkeeping path VIABLE with existing
API only: max ΔH 0.673333 bit from one elimination, 9.7x the largest evidence
event (0.069654 bit), and a NEGATIVE ΔH control (−0.185269, softening). This
change is the SETTLEMENT-side writer of `ledger.pqs`; #250 (in flight, PR #271)
owns the mint-time writer in plan_epistemics — the two must compose, so the
seeding here is idempotent (get-or-seed).

## What Changes

1. **PQ settlement face** (`scripts/oracle_runner.py`): `record_posteriors`
   additionally drives `record_pq_updates(ws, report, led)` — for every
   settled case (verdict pass/fail), the case's optional `target_pq` +
   `pq_update:` declaration select the situational PQCategorical and the
   events to apply: `green_up`/`red_up` (candidate -> strength,
   `update_evidence` on pass/fail respectively) then `eliminate_on_pass`/
   `eliminate_on_fail` (`update_eliminate`). Per event: entropy snapshot
   BEFORE (update_* mutate in place, return None), apply, record signed
   `delta_h_bits = h_before − h_after` plus `h_standing_bits` as separate
   fields. One ledger save per run, unchanged contract otherwise.
2. **Idempotent seed**: a settled question with no categorical in
   `ledger.pqs` is seeded uniform from the task_spec `primary_questions[]`
   entry whose `id` equals the pq_id (candidates presence is the signal).
   An existing pq is never reseeded (#250 overlap tolerance). pq_id is the
   `answers_question`/`target_pq` string priority_ratio keys on — no new
   identifier namespace.
3. **Signed-ΔH convention pinned** (design D2): `delta_h_bits` is SIGNED
   information gain (softening events are negative); standing entropy is
   the separate `h_standing_bits` field (the priority_ratio `dh` quantity).
4. **Fail-open with annotation** (design D1): an unmatched candidate name
   (KeyError from update_*) is skipped and annotated — never crashes the
   settlement path. Same for eliminating the last surviving candidate
   (design D3): annotated no-op, not a ValueError into the reward path.
5. **Event face**: one `pq_posterior_update` event per applied/skipped PQ
   event (new registered EMIT_ACTIONS word) carrying case_id, pq_id,
   channel, name, strength, h_before/h_after/delta (6dp), status, reason.
6. **Fixture committed**: `tests/fixtures/exp3_delta_h.json` — the EXP-3
   spike's exact call sequence + 6dp expected values; the new suite
   `tests/test_settlement_pq_257.py` (fast tier) asserts the wiring
   reproduces them.

## Out of Scope

- `scripts/plan_epistemics.py` and any mint-time pq writer (#250, PR #271 —
  must not be created or imported here).
- `scripts/priority_ratio.py` (read-only consumer; LAMBDA_DH stays the only
  parameter until the situational distribution exists — #250).
- `scripts/posteriors.py` library changes (spike verdict: pure plumbing).
- load_cases admission lints for `pq_update:` (settlement-side reader is
  tolerant per-file; a malformed bookkeeping declaration must never refuse
  the run face — liveness first).
- ΔH consumption/retuning in the ranker formula (#251 owns the seed
  contract there).
