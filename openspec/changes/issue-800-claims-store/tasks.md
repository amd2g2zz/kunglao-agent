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
