# issue-796-phi-tree-v2 — tasks

1. [x] SDD: openspec change directory (this change), `openspec validate` clean
2. [x] RED: `tests/test_phi_tree_796.py` — the three-scenario replay
   E2E (3 > 2 > 1 ranking contract) + panel pre-conditions (chain
   multiplier inside Φ, regime stamp, uniform birth mass, signed
   clawback outside the credit stream) + adversarial patches (decisive
   gate vs straw-man farming, escrow timing, store mirror, L9 censor)
   + dilution ban + valuation/attribution pairing
3. [x] GREEN: `scripts/rlvr/phi_tree.py` (tree Φ, decisive gate,
   settle_resolution escrow+attribution, clawback+mirror,
   elimination_credit, reconcile_claim)
4. [x] GREEN: `scripts/hypothesis_store.py` schema v2 (parent_id,
   posterior, critical_path, resolved evidence/attribution; v1
   round-trip byte-identical)
5. [x] GREEN: `scripts/rlvr/incremental_reward.py` Φ swap (tree dim in,
   facts dim out, potential-based, phi_regime stamp, reconcile wiring
   on terminal closes)
6. [x] GREEN: `references/contracts/reward-rules.yaml` v4
   (hypothesis/decisive-resolution + hypothesis/churn rule classes)
7. [x] GREEN: L9 fold-in — refutation_fold absorbed rows ride censored
8. [x] registration: rlvr facade + README map rows, consolidated_ledger
   NATIVE_SCHEMAS stamps, baselines emit FIRST
9. [x] deploy_manifest --write LAST; targeted suites green (`-n 4`),
   quality gates ALL-PASS, impact+detect-changes, mint chain
   (kunglao-w2-796), push, PR — all green, report stop, no merge
