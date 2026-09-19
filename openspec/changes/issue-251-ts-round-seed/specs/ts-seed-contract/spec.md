# issue-251-ts-round-seed — spec delta: ts-seed-contract

## ADDED Requirements

### Requirement: Replayable (posteriors, round) seed

The Thompson seed SHALL be a pure function of the CASES posterior state
and the round: sha256 over `{"cases": {id: {alpha, beta, pending_entries}}
sorted-by-id, "round": int}` (canonical json, sort_keys). The same inputs
MUST produce identical rankings and identical rng_base (byte-replayable
from the rank_feeds tail).

#### Scenario: replay

- **WHEN** two runs read the same posteriors doc and the same round
- **THEN** both rankings and both rng_base values are identical

### Requirement: Raw-count round accessor

The round SHALL be the RAW snapshot-row count of
`<ws>/.convergence_ledger.jsonl` (dict rows with no `type` key and an
`open_count` key — mirroring convergence_health's snapshot filter). The
deduped `assess()["rounds"]` value MUST NOT be used (wall-clock leak).
Missing/empty/corrupt/non-dict rows SHALL be handled deterministically
(via kunglao_log.iter_jsonl skip semantics plus a dict isinstance guard).

#### Scenario: dedup divergence

- **WHEN** two same-state snapshots land within the dedup window
- **THEN** round_index counts 2 and assess()["rounds"] reports 1 — the
  seed MUST follow round_index

### Requirement: Per-round cold start

An empty or absent posteriors ledger SHALL hash `{"cases": {}, "round": n}`
— distinct rounds produce distinct seeds. No constant-seed short-circuit
(such as `Random(0)`) SHALL exist on any path.

#### Scenario: cold start unfreezes

- **WHEN** the posteriors ledger is empty and rounds advance 0,1,2,3,4
- **THEN** five distinct seeds (and five distinct rng_base values) result

### Requirement: Threaded round telemetry

rank_feeds input_fingerprint SHALL carry `round` beside `rng_base`.
Production callers SHALL thread the seed round (posterior_seed_state); the
emit SHALL NOT re-read the ledger when threaded. The None fallback
(static-fixture callers only) resolves INSIDE the emit's fail-open try —
an accessor failure SHALL lose only the telemetry event, never the
ranking (#569).

#### Scenario: accessor failure is fail-open

- **WHEN** round_index raises on the fallback read inside the emit try
- **THEN** the ranking still returns in full and the failure is recorded
  to the emit-fail health file (#569), never raised to the caller
