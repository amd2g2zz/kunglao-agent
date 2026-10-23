# issue-800-claims-store — claims_store: one state owner with a legal-transition matrix

## Why

Claim state is mutated as a side-effect of gate passage by whoever is
passing, with compensation instead of ownership (#800, design-review
FATAL). `status_defs.py` owns the vocabulary; NOBODY owns the
transitions. The dispatch approval+flip+step-open sequence is a
hand-rolled saga across two hook processes, and dispatch_gate's rc=2
fail-open triple undo (`undo_dispatch_anchor` →
`reopen_claim_no_worker` → `cancel_step_open`) is its compensation
face. #623/#624/#690 are this one defect.

## What Changes

1. **NEW `scripts/claims_store.py`** — the single semantic owner of
   claim-state transitions for the dispatch lifecycle. Centerpiece: the
   declared `LEGAL_TRANSITIONS` matrix (status × event → status,
   DEFAULT-DENY for every undeclared pair). One `apply()` semantic
   mutator; every applied AND refused transition lands a provenance row
   (`runs/claims-provenance.jsonl`, schema `claims-provenance/1`).
   Status sets keep coming from `scripts/status_defs.py` (designated
   vocabulary module; terminal statuses carry NO outgoing edges).
2. **The dispatch transaction** — `begin_dispatch` writes an intent
   journal (`runs/.claims-intent.json`, schema `claims-intent/1`)
   BEFORE the first write; `commit_dispatch` applies the steps
   (anchor append → launch stash → ONE atomic register rewrite
   carrying status flip + evidence_tier_attempted + dispatch_count)
   with per-step journal marks and per-file tmp+rename;
   `abort_dispatch` inverts exactly the applied steps from the journal.
   Atomicity mechanism (chosen, per spec): **intent journal + verify**
   — not a cross-file lock. Crash recovery (`recover`, run on store
   entry): a journal whose owner pid is dead or whose ts exceeds the
   window is rolled back to the journal's before-image.
3. **dispatch_gate** — the rc=2 triple-undo block is DELETED; its rc=2
   face is one journal-driven `claims_store.abort_dispatch`; rc=0
   confirms (clears) the journal. The saga names are grep-clean.
4. **worker_budget_sinks approval tail** — `_flip_claim_in_progress`,
   `_write_eta_at_dispatch`, and `_open_step` fold into
   `begin_dispatch`+`commit_dispatch`; the register's three fields
   (status / eta / dispatch_count) move in ONE rewrite instead of
   three.

## Out of scope (named)

- Settlement-side register writers (`rlvr/step_grain` bump/cancel,
  rollup, retract_claim, dead_letter, claim_expiry, mission_stall)
  keep their faces this wave — those files are other waves' exclusive
  property (W0-1/W3-1). Routing them through `apply()` is the declared
  follow-up; `cancel_step_open` stays defined (its #690 pins live in
  test_step_grain_690) but loses its last gate caller.
- Issue pin "#721 consolidation switched 4/4 under the store":
  `rlvr/consolidated_ledger.py` is W0-1's file; the 4/4 switch is
  tracked by plan row W3-1. Declared remainder for this card.
- `scheduled_tasks.json` single owning key (#679): no scheduled-tasks
  writer exists under this card's owned files; follow-up named.
