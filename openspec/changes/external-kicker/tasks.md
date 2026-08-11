## 1. Setup

- [x] 1.1 Branch `external-kicker` off `dev` baseline 532a336 (one issue / one PR / one branch / one worktree)
- [x] 1.2 Baseline: scripts/ 179 passed; tests/ 231 passed + 6 pre-existing failures + 1 skipped (recorded; do NOT fix)

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 proposal.md (why: dead-session recovery must not depend on presence; 坑 7 — wire_up_settings.py:20 user-level mis-wiring is the T1 root cause)
- [x] 2.2 spec.md (REQ: dead-session detection / interval < TTL / project-level hooks env-preserving / exactly-one-winner competition / pure command construction / kick record)
- [x] 2.3 design.md (D1-D6 + R1-R5 rejected)
- [x] 2.4 tasks.md
- [x] 2.5 `openspec validate external-kicker` PASS

## 3. RED tests (write first, must fail)

- [x] 3.1 `test_session_is_dead_*` (missing / both-stale / fresh-last-tick / fresh-activity / unparseable)
- [x] 3.2 `test_ensure_project_hooks_*` (env+other keys preserved / legacy replaced / other matchers preserved / idempotent)
- [x] 3.3 `test_acquire_kick_lock_*` (fresh lock skips / stale replaced / concurrent create loses)
- [x] 3.4 `test_has_fresh_workers_*` (fresh in-progress / stale in-progress / done)
- [x] 3.5 `test_build_schtasks_command` / `test_build_crontab_line` / `test_build_kick_command`
- [x] 3.6 `test_tick_interval_must_be_lt_ttl` (30 min → exit 1)
- [x] 3.7 `test_tick_kill_session_then_kick` (dead session + dry-run → kick record + prompt file + project settings rewritten with env preserved)
- [x] 3.8 `test_tick_skips_when_alive` / `test_tick_multi_start_exactly_one_winner` (lock held → second tick skips)
- [x] 3.9 Confirm RED: `python -m pytest scripts/test_external_kicker.py -q` — collection error (module missing)

## 4. GREEN — scripts/external_kicker.py

- [x] 4.1 `session_is_dead(heartbeat, now, stale_minutes)` — D1
- [x] 4.2 `ensure_project_hooks(settings, hook_dir)` — D2 (5 entries, basename dedupe, POSIX paths, env-preserving)
- [x] 4.3 `acquire_kick_lock` / `release_kick_lock` — D3 (O_EXCL + mtime staleness)
- [x] 4.4 `has_fresh_workers(runs_dir, fresh_minutes)` — D3 (last status line `in-progress` + mtime)
- [x] 4.5 `build_kick_command` / `build_schtasks_command` / `build_crontab_line` — D4/D5
- [x] 4.6 `tick()` orchestration + interval gate + atomic settings write (tmp→replace) + kick record — D6
- [x] 4.7 CLI `main()` (workspace, --tick-interval-min, --settings, --claude-bin, --stale-minutes, --dry-run)

## 5. Docs + validation

- [x] 5.1 `python -m pytest scripts/test_external_kicker.py -q` → 34 passed
- [x] 5.2 `python -m pytest scripts/ -q` → 213 passed (179 baseline + 34 new, no regression)
- [x] 5.3 `python -m pytest tests/ -q` → 231 passed + 6 pre-existing failures unchanged
- [x] 5.4 `openspec validate external-kicker` PASS

## 6. Commit

- [x] 6.1 Commit SDD artifacts: `sdd(external-kicker): OS-level dead-session recovery — proposal/design/spec/tasks (#39)`
- [x] 6.2 Commit impl + tests: `feat(external-kicker): OS-level dead-session recovery — project-level hooks + lock competition (#39)`
