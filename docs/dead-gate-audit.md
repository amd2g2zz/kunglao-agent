# Dead Gate Audit (#119 / S2-1)

## Result: All 5 gates are MANUAL-BY-DESIGN — no deletions

| Gate | Verdict | Evidence |
|------|---------|----------|
| plan_drift_detector.py | KEEP (manual) | 5 references in case-book.md + failure-modes docs with run guidance |
| stale_blocker_prune.py | KEEP (manual) | 5 references in failure-modes docs with run guidance |
| claim_expiry.py | KEEP (manual) | 5 references in failure-modes docs with run guidance |
| provenance_gate.py | KEEP (library) | 10+ tests in test_provenance_gate.py, imported as library function |
| report_consistency_check.py | KEEP (library) | Tests in test_report_consistency_check.py, imported as library function |

## Rationale

- Gates 1-3 are intentionally manual: docs specify "run when X happens"
- Gates 4-5 are library functions with dedicated test suites
- None are dead code — all have clear use cases and documentation
