# Tasks

- [x] Phase 0 — read `scripts/loop_scheduler.py` (`_read_entries` / `_write_file` / upsert) + existing test patterns (`test_heartbeat_autonomy_754.py` r3-M1 contracts)
- [x] Phase 1 — RED: `tests/test_scheduler_schema_679.py` (4/4 failed, reproducing the tasks-key destruction + `.unrecognized-*` exile)
- [x] Phase 2 — T2 `_read_entries` accepts `tasks` + `jobs` + bare array (jobs-first when both ride one doc)
- [x] Phase 2 — T3 `_write_file` preserves original container key + unknown sibling keys in place
- [x] Phase 2 — T4 negative control: `{"tasks":[...]}` through upsert, harness array byte-identical (4/4 GREEN)
- [x] Regression — `test_heartbeat_autonomy_754.py` / `test_slot_monitor_636.py` / `test_harness_common_863g.py` / `test_loop_prompt_split_434.py` (85 passed)
- [x] Gates — `ruff check` clean; `comment_hygiene_lint --emit` + `formal_code_lint --emit-baseline` + `deploy_manifest --write` re-emitted (both lint checks rc 0)
- [x] Phase 3 — OpenSpec `issue-679-scheduled-tasks-schema` (proposal / design / tasks / specs)
- [x] Phase 4 — `openspec validate issue-679-scheduled-tasks-schema`
- [ ] detect_changes pre-commit check + commits ≤ 300 lines + PR + CI (-n 4 local cap; full suite in CI)
