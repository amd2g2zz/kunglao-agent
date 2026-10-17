# tasks — issue-733-arming-shape-law

## 1. The RED contract

- [x] `tests/test_arming_shape_733.py`: three pins — the old mapping
      shape is no longer armed while the runner's list shape is; the
      predicate and the parse agree across a ten-shape probe matrix
      (the predicate is the law, not a lossy copy, and is not
      re-derived locally); the amendment observes only the canonical
      shape end-to-end
- [x] confirmed RED before implementing (3 failed; the dict shape was
      armed and `expected_shape_error` did not exist)

## 2. The one law

- [x] `scripts/oracle_runner.py`: public `expected_shape_error(raw)`
      (first shape fault or None); `_parse_expected` delegates its
      shape half — every raise text-identical to pre-refactor (probe-
      matrix pinned) — and keeps the #126 workspace-resolution half
      unchanged
- [x] `scripts/settle_round_credit.py`: `_arming_field_present`'s
      `expected` branch delegates to the same predicate (dict shape no
      longer armed — the intended tightening)

## 3. Fixtures

- [x] `_armed_case` (`test_reward_source_678`), `_armed_case_doc`
      (`test_rl_output_path_691`), `_armed_case`
      (`test_late_arm_oracle_730`) migrated to the canonical shape

## 4. Gates

- [x] GitNexus impact: `_parse_expected` upstream = CRITICAL (117
      impacted, 30 processes, 20 modules — the oracle pipeline);
      refactor is raise-semantics-preserving and gated by the oracle
      suites (108/126/132/303 all green) plus the new shape-matrix pin
- [x] 76 passed across the six affected suites
- [x] `openspec validate issue-733-arming-shape-law` exit 0
- [x] ruff / formal-code / comment-hygiene clean

## 5. Follow-ups (data, not this repo change)

- [ ] Re-author the live workspace's four armed case docs into the
      canonical shape (per-case domain judgement: real stage
      field/value, or an explicit `pending-observation` marker) —
      until then their amendment observations honestly stop
- [ ] `scripts/README.md` oracle_runner row: note the exported shape
      law if the row gains an API description
