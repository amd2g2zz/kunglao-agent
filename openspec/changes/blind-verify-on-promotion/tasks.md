# Tasks — blind-verify-on-promotion
- [x] 1. OpenSpec scaffolded
- [x] 2. RED: tests/test_blind_gate.py (15 tests, all RED initially)
- [x] 3. GREEN: scripts/blind_gate.py (check_proven_gate + extract_verifier_signoff)
- [x] 4. GREEN: wire blind_gate into kunglao_record.claim_migrator
- [x] 5. GREEN: wire blind_gate into worker_budget.compare_register_change_proven_gate
- [x] 6. GREEN: tools/measure_blind_coverage.py
- [x] 7. pytest 196 passed + 1 skipped (was 182; +15 new, 0 regressions)
- [ ] 8. openspec validate PASS
- [ ] 9. PR -> dev
