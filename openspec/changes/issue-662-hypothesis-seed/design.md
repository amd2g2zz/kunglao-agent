# Design — hypothesis seed (#662)

## D1. Seeding model

Mechanical scaffold, no analysis content (mirrors init's #412 rule — init
performs no analysis; neither does the seeder):

```
for each (qid, need) in task_spec.primary_questions:
    if any open hypothesis body contains marker "pq:<qid>":  skip (idempotent)
    else: write H-NNN:
        id: H-<next free 3-digit>
        claim_id: C-PENDING        # placeholder — replaced when the PQ's
                                   # answering claim is registered
        competitor_group: pq-<qid>
        candidates: []             # orchestrator fills BEFORE first C-NN dispatch
        status: open
        body: |
            pq:<qid>

            Seeded from primary_question <qid> (need: <need>). Scaffold only —
            the orchestrator fills `candidates` with competing explanations
            BEFORE dispatching the first C-NN for this question. Adjudicate by
            refute (refuting_fact_id) or supersede (superseded_by) per #528.
```

`candidates: []` is deliberate: a mechanical seeder must not invent
hypotheses ("Cobalt Strike" vs "custom crypto" is analyst knowledge). The
scaffold's job is to make the empty layer visible and to give the
cold-start digest a non-empty sec_g the session cannot silently skip.

## D2. Idempotency marker lives in the BODY

`HypothesisStore._write` serializes ONLY known frontmatter fields
(id/claim_id/competitor_group/candidates/status/refuting_fact_id/superseded_by)
plus the body. Any extra frontmatter key a seeder wrote would be silently
dropped on the first `transition()` — so the `pq:<qid>` marker is embedded
in the body (line 1), which survives every rewrite. `list_open()` +
`"pq:<qid>" in h.body` is the idempotency check.

## D3. claim_id placeholder

`HypothesisStore._parse` requires `claim_id` non-empty. At seed time the
answering claim does not exist yet (seeding precedes claim registration),
so the scaffold carries `claim_id: C-PENDING`. The orchestrator replaces
it when registering the PQ's first claim (a one-line file edit; the store
tolerates it — parse only checks presence). The digest sec_g lists
claim_id as-is; `C-PENDING` reads as "link pending" to the cold-start
session, which is exactly the truth.

## D4. Wire point: digest build (mechanical, every cold start)

`build_digest` already reads hypotheses for sec_g (fail-open, #528). The
seeder call goes immediately BEFORE `build_sec_g`:

```
# ---- sec_g: seed-then-list (#662) — FAIL-OPEN ----
try:
    from hypothesis_seeder import seed_from_task_spec
    seed_from_task_spec(ws)
except Exception:
    pass  # seeding failure never blocks cold start
```

Why digest and not init: `task_spec.yaml` frequently post-dates init
(#449 needs-first intake); the cold-start digest runs AFTER task_spec
exists and runs EVERY session — the seeding guarantee
("≥1 H-NN per PQ before any C-NN dispatch") holds at every entry point,
not just first init. Init-time seeding (when task_spec already exists) is
left to the orchestrator prompt — the digest re-seed backstops it.

## D5. DRAIN gate: OPEN_HYPOTHESIS_AT_CLOSE

Per #443's explicit state machine, additive:

```
STAGE_PROBES[State.DRAIN] = (
    ORPHAN_TERMINAL_CLAIM, PRIMARY_Q_UNVERIFIED, NOTE_LAYER_GAP,
    OPEN_HYPOTHESIS_AT_CLOSE,          # ← inserted
    DISCOVERY_UNCONSUMED, GLOBAL_CONTRADICTION, ANOMALY_DETECTED, DRAIN_CLEAN,
)

TRANSITIONS[(State.DRAIN, Event.OPEN_HYPOTHESIS_AT_CLOSE)] = (
    State.BLOCKED, _act_open_hypothesis)
```

Placement rationale: same completeness class as NOTE_LAYER_GAP (a delivery
prerequisite the register doesn't track) — before DISCOVERY/CONTRADICTION
(cheaper probe first; discovery/contradiction scan facts, this scans
hypotheses/).

Predicate `_open_hypothesis_at_close(s)`: `bool(s.open_hypotheses())`
where `_DecideInputs` gains a lazy+cached `open_hypotheses()` that reads
`hypothesis_store.HypothesisStore.list_open()`.

Fail-open applies to LAYER ERRORS only (unreadable dir / parse explosion →
[] → gate silent). Genuinely-open hypotheses BLOCK — that is the feature,
not a failure mode.

`_act_open_hypothesis(s)`: "Cannot CONVERGE: N open hypothesis(ies) H-001,
H-002 — adjudicate before delivery (refute via refuting_fact_id /
supersede via superseded_by, per #528 state machine). Scaffold
candidates=[] must be filled or refuted."

Verdict `BLOCKED` (delivery prerequisite, not wait-state).

decide() output gains `open_hypotheses: [...]` + `open_hypothesis_count`.

## D6. CLI + observability

```
python scripts/hypothesis_seeder.py <ws> [--json]
```

exit 0 = seeded or already-seeded (idempotent); 2 = usage error. Each
write emits one `kunglao_log` event (action=`hypothesis_seed`,
detail=`H-NNN pq:<qid>`), mirroring anomaly D6 posture.

## D7. Fail-open layers

- digest wiring: seeder exception → pass (cold start proceeds)
- seeder on missing/unparseable task_spec: return [] (convergence's
  existing INVALID path handles malformed PQ schema at its own layer)
- DRAIN gate on unreadable hypotheses/ dir: [] (no block)
- DRAIN gate on genuinely-open hypotheses: BLOCKS (that is the feature,
  not a failure mode)

## D8. Test strategy (RED-first)

- RED1: seed creates one scaffold per PQ (marker, status, competitor_group)
- RED2: idempotent (second run adds nothing; marker survives HypothesisStore rewrite)
- RED3: no task_spec → [] no crash
- RED4: malformed task_spec → [] no crash
- RED5: digest integration — build_digest seeds then sec_g lists the scaffold
- RED6: convergence DRAIN → BLOCKED with open hypothesis at close, reason names H-id
- RED7: hypothesis refuted (refuting_fact_id) → DRAIN clean
- RED8: C-PENDING placeholder + candidates=[] per D1/D3
