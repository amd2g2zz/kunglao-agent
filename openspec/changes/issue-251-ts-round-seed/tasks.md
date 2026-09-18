# Tasks — issue-251-ts-round-seed

- [x] EXP-1 spike: accessor ruling (raw row count, not assess()["rounds"]),
      P2 frozen evidence (5/5 identical rankings, 1 distinct rng_base),
      v2 payload design — posted to #251
- [x] RED: 10 tests lifted from the spike (accessor filter, raw-not-dedup
      pin, ledger-name equality, P1 replayable, P2 seed-liveness and
      ranking-liveness asserted separately, P3 posterior sensitivity,
      cold-start direct + production, rank_feeds round telemetry) —
      10/10 failed pre-implementation
- [x] GREEN: `round_index(ws)` accessor; `case_face_seed(ledger, round_no)`
      hashes `{"cases": {...}, "round": n}`; `Random(0)` branch deleted
- [x] rank_feeds input_fingerprint gains `round` (hash-covered)
- [x] Review R2 fixes: threading (`posterior_seed_state`, both production
      callers), param shadow rename, docstring honesty
- [x] Review R3 fix: None-fallback re-read moved inside the emit's
      fail-open try (#569 probe-proven)
- [x] test_algorithm_event_log_157 canon + round key
- [x] test_budget_channel_862 fixture order-agnostic (v1 cold-start order
      pin replaced by production-derived claim selection; deviation-gate
      contract untouched)
- [x] test_value_rebuild_107 signature pin extended to the 5-param
      contract (rng, round_no both default None)
- [x] full fast tier green; ruff clean; three adversarial review rounds
      APPROVE (final content sha recorded in the review evidence)
