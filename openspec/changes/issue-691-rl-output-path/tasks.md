# tasks — issue-691-rl-output-path

## 1. T2 — the declaration reconciliation (gate + usage row)

- [x] `scripts/method_families.py` `append_usage_row`: keyword-only
      additive `propensity` / `sampled_family` / `prior_source`
      (boundary-validated, explicit-null stable schema)
- [x] `scripts/rlvr/strategy_store.py` `reconcile_declaration(ws,
      declared)`: the gate's own draw (method_sample) + the declared
      family's draw probability; all-None gap view on every miss
      (fail-open + warn)
- [x] `hooks/worker_budget_sinks.py`: `_sample_reconciliation` +
      `_emit_sample_deviation` helpers wired into `_method_family_gate`
      after vocabulary validation (reconciliation never rejects)
- [x] `scripts/event_taxonomy.py`: `sample_deviation` registered in
      EMIT_ACTIONS (sorted + unique)
- [x] RED: `test_declared_family_records_propensity_and_sampled_family`,
      `test_deviation_from_sample_is_recorded_not_silent`,
      `test_agent_reasoning_bypass_emits_sample_deviation_event`

## 2. T3 — the labeled prior + ONE draw implementation

- [x] `PosteriorStrategyStore.proposal_prior_labeled()` → (prior,
      source ∈ history | llm_prior | none) — `_proposal_prior` itself
      unchanged (signature + tests pinned)
- [x] `method_sample(fp)`: the receipt-bearing twin of `method_lead`
      (same chain/seed/kwargs) + additive `prior_source` label;
      `method_lead` delegates
- [x] intake branch covered by the label path (registry wall via
      `_registered_only`, share-normalized; the #544 tolerant read maps
      a missing/corrupt doc to empty silently — warn only if the seam
      itself raises)

## 3. T4 — CasePosterior → claim ranking verification

- [x] `test_case_posterior_moves_claim_rank_after_settlement`: cold
      linked rank (`Thompson Beta over 1 linked`, no ledger yet) →
      REAL `record_case_settlements` passes move the linked posteriors
      → rank order flips; the settlement writer generates
      `runs/posteriors.yaml` (the #678 arming stands in)

## 4. Verification

- [x] RED run first: 3 failed / 1 passed (T4 green pre-change — the
      wiring it verifies already landed)
- [x] targeted suites green: `tests/test_rl_output_path_691.py` 4/4
- [x] neighbor suites green (411 tests): method_families_432,
      strategy_compose_431, event_stream_adoption, ws3_compose_lead_544,
      ws3_intake_prior_544, q_cells_429, rl_wiring_518,
      event_wirings_434, gate_residuals_427, registry_admission_546,
      assembly_history_700, claudemd_g2g3_758, rlvr_bitexact,
      eval_loop_closure_523, priority_ratio, gate_failclosed,
      credit_settle_634, fact_certification_651,
      orchestration_event_taxonomy, feature_prior_460b,
      rlvr_termination_461, dispatch_contract, dispatch_protocol
- [x] ruff clean on all touched files (+ the Phase-4 file set)
- [x] comment-hygiene / formal-code lints re-emitted, both rc 0 in
      check mode
- [x] deploy manifest re-emitted (`--write`, 555 entries)
- [x] `openspec validate issue-691-rl-output-path` exit 0
