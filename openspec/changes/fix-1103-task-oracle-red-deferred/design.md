# Design — fix-1103-task-oracle-red-deferred

## Context

The settlement engine (`scripts/rlvr/reward.py classify`) is
data-driven: it reads `references/contracts/reward-rules.yaml` and
matches machine signals against rule predicates. No engine change is
needed — the defect lives in the table's data. The orchestrator
pre-validated the alternative (wiring a scalar fallback) as dead: the
v1 band=NEUTRAL gate (`scalar.py:395-400`) and the classify_tier
anti-pollution gate (`scalar.py:324-325`) both force NEUTRAL for the
zero-corroboration dimensions in this signal set.

## Goals / Non-Goals

- Goal: `[DEFERRED, fail]` settles SETTLED_RED `task/oracle-red` through
  the pure classify face; the table documents why.
- Non-Goals: no backfill of the 4 historical NEUTRAL rows; no mainline
  ΔV change (owner ruling pending); no strategy_arm/method_choices
  signal producers (separate slice); no #988 production call site (S13
  plan item).

## Decisions

- **Rules-table-only fix (no .py change).** classify is a pure
  data-driven matcher; a one-token list edit is the smallest surface
  that cannot drift from the engine. Alternative (scalar fallback
  wiring) rejected — two gates make it provably ineffective (see
  Context).
- **Keep the dual-signal shape.** `task/oracle-red` still requires BOTH
  `oracle_verdict=fail` AND `claim_terminal` in the accepted set — the
  "no single signal settles a band" doctrine is untouched, and
  PROVEN+oracle-fail stays NEUTRAL (0 recorded instances; deliberately
  not extended).
- **Version 4 -> 5 with a description paragraph.** A rules-table
  semantic change bumps the versioned file per the issue-379 precedent;
  the paragraph names issue 1103 and states that reward values and
  polarities are unchanged.

## Risks / Trade-offs

- [Version pins break] → the three `version == 4` assertions are
  updated to `== 5` in the same change; the verification run covers the
  two pinned files outside the task's four-file list.
- [DEFERRED widens the red rule] → DEFERRED + fail is a real failure
  recording today; widening only matches rows that previously fell to
  NEUTRAL (no reward-value change, only band/polarity classification).
- [Prior feed gains beta counts] → intended: negative polarity rows now
  feed the beta count that was silently empty.

## Migration Plan

Single commit, no data migration. Rollback = revert the one YAML edit
and the version pins; no persisted state changes shape (settlements are
append-only ledger rows — none were written with the old rule against
this signal set, since it settled NEUTRAL).

## Open Questions

(none)
