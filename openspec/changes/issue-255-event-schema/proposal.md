# issue-255-event-schema — mechanically populate AUTO_NULL_FIELDS + tick-stamp all events

## Why

Issue #255 (milestone v0.1.5.post2). The unified event log's schema carries
five mandatory-by-intent fields that spent their whole life null: the rot
audit measured arm / epoch / hypothesis_ref / matched_rule / duration_ms at
100% null across the 382 live rows — "exists but always null is not a stable
schema, it is rot". Population must be MECHANICAL (from execution structure,
never model diligence): timing wrapper for duration_ms, tick for epoch, actor
/action context for arm, settlement structure for hypothesis_ref /
matched_rule. Tick-stamp every event on the single time axis (round := tick
alias per the #251 owner ruling) — derived views only, no second counters.

## What Changes

1. **Tick axis in the log sink** (`scripts/kunglao_log.py`):
   `current_tick(ws)` — the convergence ledger's raw snapshot-row count
   (the #251 round contract, pinned equal to the writer's
   `convergence_check.LEDGER_NAME` by test), memoized per (path, mtime)
   like the trace-inheritance read. Absent ledger = the real cold-start
   tick 0; stat-succeeds-but-read-fails = honest None, documented at the
   emit face as `tick_ledger_unreadable`. Plus the timing wrapper pair:
   `monotonic_ms()` and the `timed()` contextmanager (perf_counter, never
   wall-clock guesses).
2. **Epoch := tick at the emit face**: an omitted epoch kwarg inherits
   `current_tick(ws)` (explicit kwarg wins); only a genuinely unreadable
   ledger leaves the null, documented — never fabricated. Every event now
   carries the single time axis by construction; there is no second
   counter, and a static producer audit (test-anchored) forbids any
   `epoch=` producer outside the schema face and the ledger-snapshot
   passthrough.
3. **Emit-site population from execution structure**:
   `rank_feeds` carries the selected arm (rank #1 claim id — the ranker
   knows its arm); `verify` carries a measured duration_ms (monotonic pair
   around the L1/L2/disasm work); `claim_settled` carries the claim's
   latest hypothesis id from the hypothesis store (the settlement's
   structural companion, fail-open).
4. **AUTO_NULL_FIELDS shrink, honesty preserved**: epoch leaves the set
   (populated-by-construction at every site that emits it); duration_ms /
   arm / hypothesis_ref / matched_rule stay — a site that genuinely cannot
   know one keeps the honest documented null ("omitted"), so the rot can
   never return as fake values.

## What Does NOT Change

- refutation_propagate.py / plan_epistemics.py — the in-flight
  hypothesis_ref-adjacent writer lane (#250) owns them; settlement sites
  there integrate via import at their own call sites when they land.
- The stable schema key set: every field stays an explicit key (nulls
  documented), old consumers keep .get().
- No back-compat shims for the old all-null rows: the ledger is append-only
  and historical rows stay as they are; only NEW events change.

## Purpose

Close the schema rot mechanically: new events carry the mandatory fields
non-null by construction where the execution structure knows them, the tick
axis stamps every event, and the null_reasons sidecar shrinks to only the
genuinely-unknowable cases.

## Impact

- Affected: scripts/kunglao_log.py (schema face), scripts/priority_ratio.py
  (arm), scripts/kunglao_verify.py (duration), scripts/register_proven_gate.py
  (hypothesis_ref), tests/test_event_schema_255.py (new), two rot-encoding
  test updates, tests/_tiers.py (fast registry), hygiene baseline tightening.
- emit() blast radius is CRITICAL (88 direct callers, 24 processes per
  GitNexus) — mitigated by the additive-only, never-raising contract: the
  signature is unchanged, no caller edit is required for the axis, and the
  tick read is memoized (one stat on the hot path).
