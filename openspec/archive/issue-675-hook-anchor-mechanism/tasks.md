# Tasks — Hook-table anchor derivation (#675)

## 1. Setup

- [x] 1.1 Worktree (issue worktree dir) branch `issue-675-hook-anchor-mechanism` off origin/dev (2b7f946 — contains #719 completion-gate fixes)
- [x] 1.2 Baseline: 4 anchor suites 61 passed — #719 did NOT redden anchors (no side-report needed)
- [x] 1.3 Hand-pin inventory: 6 points (wire_up count + list; heartbeat list + double-reg count; env_check _write_settings groups; external_kicker 3/2 splits)
- [x] 1.4 Mechanism check: scripts-side `derive_hook_subset` (#381) exists, tests-side derivation absent → PR path

## 2. OpenSpec (SDD)

- [x] 2.1 proposal.md (with verification table)
- [x] 2.2 design.md (D0-D4)
- [x] 2.3 specs/hook-anchor-derivation/spec.md
- [x] 2.4 tasks.md

## 3. TDD — RED (drift demonstration, scratch edit never committed)

- [x] 3.1 Scratch-edit registry (`zz_fake_probe_675.py` in `WIRE_UP_HOOK_FILES` + matching `_ensure` in `register_hooks`), run anchor suites → capture the RED output (the #608 signature: count mismatch + basename mismatch + heartbeat counts)
- [x] 3.2 Revert scratch edit

## 4. TDD — GREEN (derivation)

- [x] 4.1 `scripts/wire_up_settings.py`: export `DOUBLE_REGISTERED_HOOKS` + D1 comment; cross-ref comment at the `register_hooks` worker_budget Post site
- [x] 4.2 `tests/test_wire_up_settings.py`: derive both anchors; add anti-repinning guard test
- [x] 4.3 `tests/test_heartbeat_bootstrap.py`: derive list + per-file expected counts
- [x] 4.4 `tests/test_env_check.py`: `_write_settings` construction guard
- [x] 4.5 `tests/test_external_kicker.py`: derive pre/post counts from `KUNGLAO_HOOK_ENTRIES`
- [x] 4.6 `tests/test_hook_registry_singlesource.py`: sentinel pin for the new export
- [x] 4.7 Re-apply scratch edit → anchor suites GREEN with zero test edits (drift eliminated proof); revert scratch edit
- [x] 4.8 Full anchor suites + affected files back to all-green baseline

## 5. Gates

- [x] 5.1 gates: 1/3/4/5/6/7 PASS; Gate 2 tool-exit FAIL (pytest exit 1, 6 failures) but LEDGER PASS — the same 6 (gate_power_473, init_deploy_env, probe_tiers x2, v012 x2) fail identically on clean origin/dev 2b7f946 (verified by direct run); zero new out-of-ledger failures
- [x] 5.2 Acceptance grep: no hook-count literals left in tests/ (sentinel + seed-fixture exceptions documented)

## 6. Commit (3-segment, staged sha reported, mint-gated)

- [ ] 6.1 Segment 1: openspec four-piece
- [ ] 6.2 Segment 2: registry export + test derivations (impl + tests)
- [ ] 6.3 Segment 3: evidence residue (none expected beyond openspec tasks checkboxes — fold into 6.2 if empty)
