# tasks — issue-678-reward-source

## 1. T2 — the cited_ids producer (deliverable citation leg)

- [x] `cited_ids_from_deliverables(ws)` — notes/, analyses/,
  runs/deliverables/ recursive scan for `F<NNN>` tokens (tolerant,
  never raises)
- [x] `fact_artifacts(ws, cited_ids=None)` invokes the producer by
  default; explicit sets keep their exact meaning
- [x] `_deliverable_cited` — exact-id leg + bare-token leg (slugged
  fact-id grammar vs bare deliverable mentions)
- [x] shim export growth (`scalar_settlement`)
- [x] RED: `test_cited_ids_producer_marks_deliverable_refs`

## 2. T3 — the creator backfill (settlement path)

- [x] `backfill_artifact_creators(artifacts, dispatch_ids)` —
  claim-id attribution for the current settlement's dispatches;
  `creditable: false` otherwise; new dicts only
- [x] wired into ws-level `settle_round_credit` + the CLI dry-run
  (grade honesty)
- [x] RED: `test_fact_without_creator_is_untraced`,
  `test_creatorless_fact_on_a_settled_claim_backfills_the_creator`,
  `test_settlement_with_credited_fact_banks_nonzero_r`

## 3. D-678.4 — TRACE observation band + verification citation leg

- [x] `q_cells.OBSERVATION_BAND_CEIL` (0.05, mirrors the TRACE rail
  top) — `fold` adds no Beta mass for credits in (0, ceil]; genuine
  0.0 still trains failure; band keys on the settled credit
- [x] verification facts cited by deliverables earn FULL through the
  T2 leg (red-team credit path)
- [x] RED: `test_trace_credit_does_not_bank_as_failure_mass`,
  `test_redteam_facts_cited_by_deliverable_earn_full_credit`

## 4. D-678.5 — Φ non-degeneracy (graded weights + phi_delta)

- [x] `fact_face.weighted_fraction` — graded rungs (1.0 / 0.5 / 0.25 /
  0.0), grammar-clean admission, #651 farm wall preserved;
  count/verified byte-identical
- [x] `potential()` reads the graded fraction
- [x] `append_transition` records `phi_delta` + `claim_ref` /
  `action_key` (additive columns)
- [x] RED: `test_phi_has_intermediate_values_with_graded_facts`,
  `test_phi_partial_certification_is_strictly_intermediate`,
  `test_transition_row_carries_phi_delta_and_claim_ref`

## 5. T5 — the oracle arm (posterior visibility)

- [x] `armed_case_ids(ws)` over the five arming fields
  (channel/hypothesis_ref/update_map/expected.evidence_refs/mutations)
- [x] every `run()` pass reports `cases_armed` + warns when zero
- [x] RED: `test_armed_case_settlement_writes_posteriors`,
  `test_unarmed_case_is_not_armed`

## 6. Re-minted pins (audit-noted in place)

- [x] state-396 fact_face exact-dict pins grew `weighted_fraction`
- [x] cert-651 junk-file fact_face pin grew `weighted_fraction: 0.0`
- [x] absorb-597 + rc1-601 bare-kill row key-set pins grew
  phi_delta/claim_ref/action_key

## 7. Verification

- [x] `uv run ruff check` clean on all changed files
- [x] targeted suites green: 678 (11), state-396, cert-651, incr-539,
  q-cells-429, round-credit 433/438, scalar-379, reward-366,
  transitions-550, launch-stash/schema-wall-654, absorb-597,
  censored-548, ope-654, dispatch-704, rc1-601 + the remaining
  import-surface sweep (~860 tests)
- [x] deploy manifest re-emitted (`deploy_manifest.py --write`) +
  `--verify`
- [x] `npx openspec validate issue-678-reward-source` exit 0
- [x] `gitnexus detect_changes` before commit
