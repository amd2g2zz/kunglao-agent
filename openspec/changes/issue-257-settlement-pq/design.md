# Design — issue-257-settlement-pq

EXP-3 spike (issue #257 comment) is the authoritative wiring spec; this
document pins the decisions the spike left open and the anchors it verified.

## Verified anchors (2026-09-18, branch fix/257-settlement-pq @ 4c800b5)

- `scripts/posteriors.py` — `entropy_bits` :50, `PQCategorical` :119,
  `update_eliminate` :148 (KeyError on unknown name, ValueError on the last
  candidate), `update_evidence` :158 (KeyError on unknown; strength<0/inf
  ValueError), `entropy` :168, `PosteriorLedger.save(ws)` :232 (atomic).
  No library changes required (spike verdict: VIABLE, pure plumbing).
- `scripts/oracle_runner.py` — `record_posteriors` :848 (touches `led.cases`
  only); settlement path = `main()` :1094 AND `oracle_cadence.py` :232/:244
  — BOTH call `record_posteriors`, so the PQ face rides inside it and both
  settlement faces get ΔH without touching oracle_cadence.
- `scripts/priority_ratio.py` :690/:714 — `pq = claim["answers_question"]`,
  `ledger.pqs.get(pq)`; oracle case linkage via `target_pq == pq`
  (`_load_oracle_cases` :511). READ-ONLY here (#251 owns the ranker seed
  contract; do not touch).
- Drift check: all spike line anchors held exactly.

## D1 — Unmatched evidence name: FAIL-OPEN with an emitted annotation

`update_evidence`/`update_eliminate` raise KeyError on a candidate name the
categorical does not carry. Ruling: **fail-open + annotation**, not loud.

Justification:
- Liveness first (house posture): the settlement path is the reward
  channel — `record_posteriors`' existing contract is "bookkeeping never
  disturbs the state write", and every observability wrapper in the file
  (`_emit_posterior_update`, `_emit_observation`, `_emit_coverage_decreased`)
  is fail-open by design. A bookkeeping declaration error crashing a real
  settlement would invert the priority.
- NOT a silent swallow: the skip is (a) recorded in the returned records
  list with `status: "skipped"` + reason, (b) emitted as a
  `pq_posterior_update` event with `status: "skipped"` — the event tail
  makes the drop auditable, matching the `oracle_cadence_warn` "never a
  silent skip" face and the `hypothesis_admission_fail_open` precedent
  (fail-open WITH a registered WARN/annotation event).
- Loud refusal is the wrong altitude here: the declaration is per-case
  optional bookkeeping, not an admission integrity face (#126 owns those,
  at load_cases, where refusal blesses the whole set — explicitly out of
  scope for this change).

## D2 — Signed ΔH convention

EXP-3b proved ΔH is NOT guaranteed ≥ 0: softening the leader with
strength<1 RAISES entropy (ΔH = −0.185269 in the fixture). Convention,
pinned by the spike's naming:

- `delta_h_bits = h_before − h_after` — SIGNED per-event information gain
  (negative = the settlement softened the distribution).
- `h_standing_bits` — the post-event standing entropy, recorded as its own
  field. This is the quantity priority_ratio prices (`dh = pq.entropy()`),
  which is why the two must never share a field name (the spike's naming-
  collision finding: priority_ratio's local `dh` is the STANDING entropy,
  not the per-event reduction).

No clamping anywhere: a "total information consumed" accumulator is not
built in this change (YAGNI — no consumer exists); consumers that want one
can sum signed events.

## D3 — Settled-PQ guard (last-candidate elimination)

`update_eliminate` raises ValueError when only one candidate remains. A PQ
that has settled to one survivor is DONE — further elimination events on it
are annotated no-ops (`status: "skipped"`, reason
`"pq already settled — single surviving candidate"`), never a crash into
the settlement path. Guard: count nonzero-mass candidates before applying
an elimination; ≤1 → skip with annotation. (Evidence events on a settled PQ
still apply — softening/confirming a decided question is legitimate.)

## D4 — Declaration shape (declarations, never inference)

The verdict alone cannot name a candidate — the case declares the PQ face:

```yaml
target_pq: q_jni_registration   # existing key = the pq_id (answers_question string)
pq_update:                      # optional; absent -> no PQ bookkeeping
  green_up:                     # candidate -> strength; update_evidence on PASS
    static_xref_dlsym: 2.5
  red_up:                       # candidate -> strength; update_evidence on FAIL
    runtime_dlopen: 0.25
  eliminate_on_pass:            # candidate names; update_eliminate on PASS
    - jni_register_natives
  eliminate_on_fail: []
```

- Apply order per verdict, pinned deterministic: evidence events
  (`green_up`/`red_up`, mapping = YAML document order) THEN eliminations
  (list order). Elimination ΔH depends on the evidence events having
  already shifted mass (the EXP-3 sequence's largest event assumes this).
- Read at settlement time from the case YAMLs (fail-open per file,
  mirroring `priority_ratio._load_oracle_cases`) — NOT through
  `load_cases`, whose refusals bless the run face. A malformed
  `pq_update` block is a per-case annotated skip, not an OracleCaseError.

## D5 — Idempotent seed (the #250 boundary)

`ensure_pq(led, ws, pq_id)`: return `led.pqs[pq_id]` when present (never
reseed — PR #271 adds a mint-time writer in plan_epistemics; both writers
must tolerate each other); else seed uniform
`PQCategorical(pq_id, {c: 1.0 for c in candidates})` from the task_spec
`primary_questions[]` entry with `id == pq_id` and a non-empty candidates
list; else None (caller annotates the skip). pq_id is the EXISTING
answers_question/target_pq string — no new identifier namespace, and
priority_ratio's `ledger.pqs.get(pq)` lights up the moment the first
categorical lands.

## D6 — Event face

One `pq_posterior_update` event per applied or skipped event (new
EMIT_ACTIONS word, sorted after `posterior_update`), detail JSON:
`{case_id, pq_id, channel: evidence|eliminate, name, strength, h_before_bits,
h_after_bits, delta_h_bits, h_standing_bits, status: applied|skipped,
reason}` — floats at 6dp for stable event text. Emission is guarded
fail-open like every emit in the file.

## Testing

RED-first against `tests/fixtures/exp3_delta_h.json` (the spike's exact
numbers, committed with this lane): evidence ΔH 0.069654, eliminate ΔH
0.673333 (largest), third evidence 0.405198, softening −0.185269 signed,
h_standing 0.337290 / 0.522559; ledger round-trip; pq_id keying equals
priority_ratio's strings; KeyError fail-open; settled-PQ guard; idempotent
seed; pending-verdict no-op. Suite: `tests/test_settlement_pq_257.py`,
fast tier. OWNER RULING: local pytest `-n 8`, never `-n auto`.
