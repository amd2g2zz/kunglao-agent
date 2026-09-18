# Proposal — issue-251-ts-round-seed

## Why

Audit of 103 rank_feeds events showed rng_base had exactly 1 distinct value
and the top claim score byte-identical 53 consecutive times: Thompson
degenerated into the old fixed ranking whenever posteriors were static —
the draw cadence was parasitic on case settlements. Cold start was a
second, independent hole: the empty ledger short-circuited to
`random.Random(0)` before any hashing, freezing the cold start regardless
of round.

Root cause: the seed was a pure function of the CASES posterior state
(sha256 of the posteriors doc) — no time axis anywhere. The #107
docstring even claimed "no clock and no counter file" as a feature.

## What changes

- Seed contract v2: `f(posterior_state, round)` — sha256 over the canonical
  cases doc PLUS `"round": n` mixed inside the hashed doc (one canonical
  payload). Owner ruling: round := tick (single time axis; round:=tick
  alias per the tick unit system).
- Round source: RAW snapshot-row count of `.convergence_ledger.jsonl`
  (`round_index(ws)` accessor; filter mirrors convergence_health.assess's
  snapshot filter: dict rows, no `type` key, has `open_count`). NEVER
  `assess()["rounds"]` — that value is `_dedup_consecutive`-collapsed on
  wall-clock proximity and would leak the clock into the seed.
- Cold start: the `Random(0)` branch is DELETED — empty ledger hashes
  `{"cases": {}, "round": n}` (per-round distinct).
- Telemetry: `round` rides the rank_feeds `input_fingerprint` beside
  `rng_base` (EXP-1 re-scoped observability); frozen detection =
  equal rng_base across advancing rounds, tail-replayable.
- Threading: `posterior_seed_state(ws) -> (rng, round)`; both production
  callers (kunglao-decide, worker_budget_core) thread the seed round into
  the emit so telemetry never re-reads the ledger (second-read race).
  The None fallback (static-fixture callers only) resolves INSIDE the
  emit's fail-open try (#569 contract held — probe-proven across three
  adversarial review rounds).

## Non-goals

- The K-repeat frozen marker CONSUMER is deferred to #266 (write-only
  telemetry as shipped is the EXP-1-ruled scope).
- No change to ranking math, candidate filter, or the per-claim fork
  scheme (`thompson/{base}/{cid}`).
