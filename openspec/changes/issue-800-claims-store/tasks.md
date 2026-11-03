# tasks — issue-800-claims-store

## 1. The RED contract
- [ ] tests/test_claims_store_800.py: illegal PROVEN→IN_PROGRESS
      refused + provenance row; wake-less PARK refused; dispatch
      transaction happy path (one register rewrite: flip+eta+count);
      SIGKILL-between-steps recovery leaves no partial state; reject
      abort inverts exactly (#623); in-flight not dispatchable (#624);
      crash-between-hooks recovery; grep-clean pin for the saga names
- [ ] confirmed RED before implementing

## 2. The faces
- [ ] scripts/claims_store.py: LEGAL_TRANSITIONS matrix + apply() +
      provenance + journal transaction (begin/commit/abort/confirm/
      recover) + native anchor append (row shape = record_dispatch_anchor)
- [ ] worker_budget_sinks approval tail routed through the store
      (three local writers folded into one register rewrite)
- [ ] dispatch_gate: triple-undo deleted; abort on rc=2, confirm on rc=0

## 3. Gates
- [ ] pins green; neighbors (test_worker_budget, test_step_grain_690,
      test_plan_first_ownership_239, test_status_defs) green
- [ ] quality_gates --quick ALL-PASS; belt fast-not-docs green
- [ ] registration triple: README row + ext-scan + deploy_manifest --write
- [ ] review-gate mint; CI green

## 4. R2 amendments (production-log panel 2026-10-23) — RED first
- [x] tests/test_claims_store_800_rollout.py keyed-ledger pin (mint ->
      ledger dispatched/committed rows + q-cell pending-row FK +
      latest_committed_dispatch) — confirmed RED
- [x] verification-ordering pins (bare refused / postdating-ts refused
      / ordered applies; decisive FAIL settlements exempt) — confirmed
      RED
- [x] terminal-idempotency pin (second decisive settle refused,
      register unchanged) — confirmed RED
- [x] missing-rollout pins (C-005 gap loud + one event; legacy-alias
      banked quiet; in-flight quiet; repetition escalates at
      MISSING_ROLLOUT_REPEAT_LIMIT then degrades to emit-silence) —
      RED, the bounded pin lands with the bounded face
- [x] faces: dispatch ledger + mint_dispatch_id + apply verification
      guard + audit_missing_rollouts (bounded) in claims_store; FK
      kwarg on q_cells.record_dispatch_observation; worker_budget
      approval tail mints + threads the id; settle tick resolves the
      real id and runs the audit tail (fail-open)
- [x] registration: event_taxonomy EMIT_ACTIONS gains missing_rollout
- [x] original #800 pins updated to the amended settle contract
      (verification reference required)
- [x] no-backcompat removal (owner ruling 2026-09-01, re-affirmed
      2026-10-23): the settle claim-alias fallback and the audit's
      alias-quiet face are DELETED — off-ledger terminal claims are a
      loud unsupported gap (excluded from the pass, off_ledger count);
      the REAL dispatch id enters at the scalar bank seam
      (_bank_q_cell_credit/_reconcile resolve it from the ledger);
      fixtures mint ledger rows (tests/_dispatch_fixture.py, pending
      True/False = banked/starved shapes)
- [ ] pins green; openspec validate green; gates; mint; CI green
