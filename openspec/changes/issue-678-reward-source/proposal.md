# issue-678-reward-source — the reward channel's trusted data source

## Why

Issue #678: every settlement banks **0.0** and the credit-to-mass
mapping turns that into a pure failure unit — the sampler is being
trained to AVOID the method families that produced the only verified
work (4 of 5 banked failure units landed on PROVEN claims). Three
provenance links are missing at once, and the S9 spike added a fourth
degeneracy: the incremental reward potential Φ(s) only ever produces
0.0 or 1.0 in live workspaces.

1. the deliverable-citation face (`cited_ids`) has NO producer —
   `cited_by_deliverable` is permanently `False` (no production caller
   ever passes `cited_ids`);
2. pre-#648 facts carry no `creator` → permanently `untraced`;
3. the declared oracle cases were never armed → `runs/posteriors.yaml`
   is never created → every case posterior stays at the Beta(1,1) wide
   prior, invisibly;
4. Φ's fact dimension is a binary certified-count and the oracle dim
   never fires, so the transition ledger records no partial progress
   (`phi_delta` was not even a field).

## What Changes

1. **T2 — the `cited_ids` producer** (`scripts/rlvr/scalar.py`):
   `cited_ids_from_deliverables(ws)` scans the deliverable trees
   (`notes/`, `analyses/`, `runs/deliverables/`) for `F<NNN>` tokens;
   `fact_artifacts(ws)` with the default `cited_ids=None` now INVOKES
   the producer (an explicit set keeps its exact meaning). The match is
   exact-id first, then the artifact id's own bare `F<NNN>` token (fact
   ids carry slugs; deliverables name the bare token).
2. **T3 — the creator backfill** (`scripts/rlvr/scalar.py`):
   `backfill_artifact_creators(artifacts, dispatch_ids)` runs inside
   the ws-level `settle_round_credit` pass: a creator-less artifact
   whose `claim_id` names a dispatch of THIS settlement attributes to
   that claim (the claim id IS the dispatch identity in the settlement
   path); anything else is explicitly marked `creditable: false`.
   New dicts throughout — the pure core sees backfilled rows only.
3. **D-678.4 — the TRACE observation band + the verification citation
   leg** (`scripts/rlvr/q_cells.py`, the ladder already terminal):
   a settled credit in `(0, 0.05]` adds NO Beta mass in `fold` (the
   information option is an observation, never a verdict; a genuine 0.0
   still trains failure); verification facts (`answers_question=None`)
   cited by deliverables earn FULL through the same citation relation
   (T2 makes that leg live).
4. **D-678.5 — Φ non-degeneracy** (`scripts/rlvr/state.py`,
   `scripts/rlvr/incremental_reward.py`): `fact_face` grows a graded
   `weighted_fraction` (grammar-clean certified terminal 1.0 /
   substantive non-terminal 0.5 / draft 0.25 / junk 0.0 — the #651 farm
   wall holds); `potential()` reads it; `append_transition` records an
   explicit `phi_delta` plus `claim_ref`/`action_key` from the launch
   stash.
5. **T5 — the oracle arm** (`scripts/settle_round_credit.py`):
   `armed_case_ids(ws)` counts cases carrying all five arming fields;
   every pass reports `cases_armed` and WARNS when zero — the silent
   "posteriors never generated" gap is now a loud, counted field.

## Impact

- Affected components: `scripts/rlvr/scalar.py`, `scripts/rlvr/state.py`,
  `scripts/rlvr/incremental_reward.py`, `scripts/rlvr/q_cells.py`,
  `scripts/settle_round_credit.py`, `scripts/scalar_settlement.py`
  (shim export growth).
- GitNexus impact: LOW on every edited symbol (fact_artifacts 5,
  fact_face 6, potential 2, fold 6, settle_round_credit 3).
- Re-minted pins (audit-noted in place): fact_face exact-dict shapes
  (state 396, cert-651) grew `weighted_fraction`; the bare-kill row
  key-set pins (absorb-597, rc1-601) grew the three additive columns.
