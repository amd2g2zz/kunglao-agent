# issue-809-verifier-integrity — tasks

1. [x] SDD: openspec change directory (this change), `openspec validate` clean
2. [x] RED: `tests/test_verifier_integrity_809.py` — the refusal replays
   (settlement-precedes-REJECT, all-reject corpus), passing-record mint,
   traversal escape, calibration BROKEN faces (loud/bounded/escalating,
   mixed/thin exempt), block-scalar faces (literal pass, folded warn,
   semantic FAIL), run-start registration faces (loud/bounded, quiet)
3. [x] GREEN: `scripts/verifier_integrity.py` (resolver + calibration)
4. [x] GREEN: `scripts/claims_store.py` — settle precondition resolves
   the reference; begin_dispatch run-start telemetry seam
5. [x] GREEN: `scripts/kunglao_verify.py` — block-scalar frontmatter +
   warn sidecar
6. [x] GREEN: `scripts/oracle_cadence.py` — `assert_run_start`
7. [x] event word `verifier_calibration_broken` registered in
   `scripts/event_taxonomy.py`
8. [x] update the #800 store tests to seed real records
9. [x] registration trio: scripts/README row, ext-scan regen,
   `deploy_manifest.py --write` LAST
10. [x] lint baselines regenerated (`--emit-baseline`), targeted suites
   green (`-n 4`), `devkit/quality_gates.py --quick` ALL-PASS
