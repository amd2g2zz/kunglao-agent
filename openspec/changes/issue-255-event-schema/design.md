# Design — issue-255-event-schema

## Context

The emit face is the highest-fan-in surface in the repo (GitNexus: 88 direct
callers, 24 processes, CRITICAL blast radius) with one hard contract: logging
must never break analysis (never raises; write failure degrades to stderr).
The design therefore changes behavior only INSIDE emit (signature unchanged)
and at three structurally-aware call sites.

## Goal / Non-Goal

- Goal: every event carries the single time axis; the five rot fields carry
  mechanical values where execution structure knows them; the auto-documented
  null set shrinks only by earned shrinkage.
- Non-Goal: retro-populating historical rows; populating fields at sites
  that structurally cannot know them (that path is fabrication); touching
  the in-flight refutation/plan-epistemics writer lane.

## Decisions

### D1. Tick accessor mirrors the ranker's round contract exactly

`current_tick(ws)` counts RAW snapshot rows in
`<ws>/.convergence_ledger.jsonl` — snapshot face: a mapping with no "type"
key carrying "open_count"; dirty lines skipped by the tolerant reader.
Rationale: the axis must be THE round contract's axis (round := tick alias),
not a second opinion. Memoized per (path, mtime) like the trace read (the
hot emit path costs one stat). Absent ledger → 0 (a real cold-start tick);
read-failure → None (honest unknowable; emit documents
`tick_ledger_unreadable`).

### D2. Inheritance at the emit face, not at call sites

epoch is inherited inside emit when the kwarg is omitted — 88 call sites
get the axis with zero caller edits, and mission_ledger's explicit-epoch
passthrough keeps winning. There is deliberately no explicit-null face for
epoch: the axis always exists (0 = cold start), so "this event has no tick"
is not a meaningful statement; explicit None is treated exactly as omitted
and the emit docstring says so. The exemption list (schema face + ledger
passthrough) is pinned by contract tests — the audit fails any new
producer file, and the passthrough shape itself is pinned so it cannot
silently become a second counter.

### D3. Timing is measurement, not guessing

`monotonic_ms()` (perf_counter, integer ms) + `timed()` contextmanager
(measures in `finally` so a raising block still records its duration). The
verify face measures its own bounded work with the monotonic pair — the
prior `duration_ms=None` was an honest-but-starved placeholder, not a wall
clock guess to keep.

### D4. Arm at rank_feeds: the selected arm, nothing more

rank_feeds is the ranker's own event; the ranker knows its arm (rank #1
claim id, actions[0] of the sorted Action list). Empty action list → None
with the honest "omitted" reason. No arm fabrication at sites without
actor/action context.

### D5. hypothesis_ref from the settlement's structural companion

claim_settled carries the claim's latest hypothesis id (max H-NNN id in the
claim's hypothesis store), fail-open: missing/unreadable store → None → the
honest documented null. Lazy import keeps the gate import-light; the
store read is O(store) on a terminal transition (rare, bounded).

### D6. AUTO_NULL_FIELDS shrink is per-field, evidence-gated

epoch leaves (populated-by-construction at every emit); the other four
stay. The set's comment now states the shrink rule (populated-by-construction
at every site that emits it) so the next shrink is earned the same way.

## Risks / Trade-offs

- [emit is CRITICAL fan-in] → additive-only change; signature unchanged;
  memoized tick read (one stat); full fast tier + affected families run
  before report.
- [tick read cost on the hot path] → memoized per (path, mtime); a ledger
  append invalidates via mtime; worst case one full-file scan per append.
- [concurrency] → same posture as the trace read: memo keyed by mtime,
  append-only ledger, worst case a slightly stale tick on a racing append
  (the axis is monotone; an off-by-one tick on a concurrent append is the
  same face the seed contract tolerates).
- [#251 merge surface] → priority_ratio.py touched by ONE line (arm at the
  emit call); the round-threading work of the in-flight round-seed lane is
  untouched and its emit-face epoch comes from inheritance, not re-read.

## Migration Plan

None needed — the ledger is append-only; historical rows stay. New rows
carry the axis. Consumers read via .get() (stable key set).

## Open Questions

- None. The owner ruling on the axis (round := tick) is already recorded.
