# issue-760-pricing-face — tasks

1. [x] RED: tests/test_pricing_760.py — unknown-set projection,
       repeat-probe/absent/retracted zero pins, high-vs-low info,
       dispatch-ledger decay, determinism, telemetry emit, consumption
       counts, cockpit block, supply-admission read
2. [x] GREEN: scripts/rlvr/pricing.py — unknown_set / price_action /
       price_for_claim / emit_price / probe_consumption
3. [x] joins: hooks/cost_input_capture.py cockpit `pricing` block;
       hooks/dispatch_gate.py `_emit_probe_price` (advisory, allow path)
4. [x] registration: rlvr export map + __all__; event_taxonomy
       probe_price / probe_price_fail_open (sorted); scripts/README.md +
       scripts/rlvr/README.md rows
5. [x] lint: comment-hygiene clean (no new ledger entries), silent-except
       clean, ruff clean on touched files
6. [x] scope fence held: no o-face ingestion, no action vocabulary, no
       composite pi, no ablation, no ranker/settlement_scorer touches
7. [ ] deploy_manifest --write LAST (ridden after baselines verified)
