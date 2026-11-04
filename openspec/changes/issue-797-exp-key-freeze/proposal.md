# issue-797-exp key freeze — task-open learning-key freeze + fingerprint churn measurement

## Why

The logs-panel review (2026-10-23) proved the Q/DTS layer's learning keys
are non-repeatable BY CONSTRUCTION: the dispatch observation recomputed
the state signature per dispatch, and every settled fact moved the
snapshot — case pq-01 cycled 3 distinct fingerprints in 35 minutes, so
signature-keyed cells never recurred and cross-run accumulation was
structurally zero (the web run re-derived C-001..C-007 from scratch
~26h after android's same-version experience started from Beta(1,1)).
21 settlements spread over 17 cells = 1.2 obs/cell: the memory cannot
learn at that density regardless of the sampler. Issue 797's acceptance
additions name the fix: (a) the cell key is frozen at task open and is
family-repeatable across runs; (c) the calibration replay also measures
fingerprint churn rate. This card lands (a) + (c) as the measurement
and freeze substrate the signature-granularity calibration experiment
(issue 797 (a)) will replay on.

## What Changes

1. **NEW `scripts/rlvr/key_freeze.py`** — the freeze + churn faces:
   - `runs/learning-key.json` (schema `learning-key/1`), mint-once per
     task: `task_signature` (the TASK ANCHOR — snapped once at task
     open via mint-on-read, immutable for the task's life) and
     `keys[family].key` (the FAMILY-grain learning key =
     `q_cells.arm_key` over structural dims only — recipe/verif/tier/
     agent, zero state-derived material — so the same-family task in
     ANY run freezes the SAME key and the fold accumulates across
     runs). Re-freeze is immutable; `other(...)` free-text escapes are
     refused at the boundary (the panel quarantine — they fragment
     cells without learning value).
   - `churn_rate(runs)` / `churn_report(ws)` — the fingerprint churn
     metric: per-run NEW vs REUSED fingerprints, churn = new/(new+
     reused); churn=1.0 (all-new, the production shape) is LOUD via the
     structured verdict; zero warn() telemetry points (Standard 11);
     an unreadable ledger is the honest gap (reason set).
2. **`rlvr/q_cells.record_dispatch_observation` consumes the frozen
   anchor** — one lazy, fail-open consult (`_task_open_signature`): the
   frozen signature when the task doc exists, the fresh per-dispatch
   computation otherwise (bit-identical legacy face). Intra-task
   accumulation is by construction; the churn source is dead.
3. **Alignment, no duplication**: issue-800's dispatch-ledger stays the
   ONE rollout identity (dispatch id) — the frozen doc keys nothing the
   ledger already keys; issue-807's INV-003 made the family the live
   posterior grain — the frozen key is family-grain by construction
   (the two cards agree on the learning grain).

## Capabilities

### Added: learning-key-freeze-797
- The task-open freeze doc and its immutability contract.
- Family-repeatable keys across runs (the cross-run accumulation pin).
- The recording face's frozen-anchor consumption with a bit-identical
  no-doc legacy path.
- The fingerprint churn measurement surface with the loud all-new
  verdict and bounded, warn-free reporting.

## Impact

- Specs: `specs/learning-key-freeze-797/spec.md`
- Code: `scripts/rlvr/key_freeze.py` (new), `scripts/rlvr/q_cells.py`
  (one additive consult in `record_dispatch_observation`),
  `tests/test_key_freeze_797.py` (new), `scripts/README.md` (registry
  row), `deploy-manifest.yaml` (regenerated LAST).
- NOT touched: ranker (issue 792), settlement_scorer (issue 802),
  supply face (issue 794), claims_store / dispatch-ledger (issue 800),
  the production-shape fixtures (issue 807), tests at large (issue 818).

## Invariants cited

- INV-003 (issue 807): the family is a live, family-level posterior
  signal — the frozen key is family-grain, never a new finer grain.
- The #429 §4 zero-decision posture: the freeze is recording/read only;
  nothing here gates, settles, or moves a dispatch decision.
- The #396 import-clean freeze: `record_dispatch_observation` keeps its
  signature computation inside the module; the consult is lazy and
  fail-open.
- Standard 11 (bounded repetition): the churn faces add zero warn()
  points; loudness is the structured verdict.
