# Tasks — state_anchor hook (#44)

## 1. Setup

- [x] 1.1 Branch `state-anchor` off `dev` 55480ee (one issue / one PR / one branch / one worktree) — worktree wt44
- [x] 1.2 Baseline measured: scripts/ 226 passed; tests/ 273 passed + 1 skipped + 6 pre-existing failures (SKILL.md 510>500, 4x test_convergence_completeness, test_acceptance meta-gate)

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 proposal.md (why: F5 forget/refresh + F1 process-level; L1 PREVENT per-turn re-anchor)
- [x] 2.2 design.md (D1-D6 + R1-R4 rejected; R1 = cross-domain reuse decision: importlib single-source over byte-for-byte mirror)
- [x] 2.3 spec.md (REQ: build_anchor / drift warning / Agent-only + FAIL_OPEN / wire-up)
- [x] 2.4 tasks.md
- [x] 2.5 `openspec validate state-anchor-hook` PASS

## 3. RED tests (write first, must fail)

- [x] 3.1 `test_anchor_contains_ledger_decision_and_open_count`: Agent completion -> anchor has last-row decision + open_count (issue TDD a)
- [x] 3.2 `test_anchor_warns_on_drift_rotation_4_no_worker`: rotation=4, no worker -> `⚠ STATE FLAT` + `4` (issue TDD b)
- [x] 3.3 `test_anchor_fail_open_missing_and_corrupt_ledger`: missing + corrupt ledger -> `""`, never raises (issue TDD c / FAIL_OPEN)
- [x] 3.4 `test_hook_skips_non_agent_tool`: tool_name Bash / Read -> empty output, rc 0 (issue TDD d)
- [x] 3.5 `test_anchor_truncates_at_500_chars`: long open-ids list -> len <= 500
- [x] 3.6 `test_anchor_excludes_progress_narrative`: fake progress.txt sentence absent (mirrors #45 RED 2)
- [x] 3.7 `test_hook_emits_on_agent_tool`: Agent tool_name + activated -> additionalContext JSON injected (mirrors worker_pulse emission)
- [x] 3.8 `test_fresh_worker_suppresses_drift_warning`: rotation>=3 + fresh worker -> no STATE FLAT (legitimate SATURATED)
- [x] 3.9 Confirm RED: `python -m pytest tests/test_state_anchor.py -q` -> 16 failed (ModuleNotFoundError: No module named 'state_anchor')

## 4. GREEN — hooks/state_anchor.py

- [x] 4.1 `build_anchor(ws)`: read ledger last SNAPSHOT + claim-register open/partial + facts count + snapshot active_workers; ≤500 chars; never raises
- [x] 4.2 Drift warning via `lib_kunglao_scripts` importlib load (`signature_rotation` + `drift_detected`); N=rotation in text; FAIL_OPEN on load failure
- [x] 4.3 `main()` / `process_event()`: stdin JSON, case-insensitive `tool_name == "agent"` gate, strict activation, additionalContext emission mirroring worker_pulse; FAIL_OPEN wraps body
- [x] 4.4 Confirm GREEN: `python -m pytest tests/test_state_anchor.py -q` -> 19 passed

## 5. GREEN — wire-up

- [x] 5.1 `scripts/wire_up_settings.py`: one-line `_ensure(post, "Agent", "state_anchor.py")` after the worker_pulse line
- [x] 5.2 `scripts/hook_activation.py::ALL_HOOKS`: add `"state_anchor"`
- [x] 5.3 Unit-test the wire-up with `Path.home()` monkeypatched to a temp dir (direct setattr — env-var redirect is unreliable on Windows); real `~/.claude/settings.json` verified unmutated (empty hooks before and after)

## 6. Validation

- [x] 6.1 `python -m pytest tests/test_state_anchor.py -q` -> 19 passed
- [x] 6.2 `python -m pytest scripts/ -q` -> 226 passed, 0 failures (no regression; the `assert added == 5` in test_external_kicker tests `ensure_project_hooks` / `KUNGLAO_HOOK_ENTRIES`, not `wire_up_settings`)
- [x] 6.3 `python -m pytest tests/ -q` -> 292 passed + 1 skipped + 6 pre-existing failures unchanged (the SAME 6: SKILL.md 510>500, 4x test_convergence_completeness, test_acceptance meta-gate; +19 net new passes, 0 new failures)
- [x] 6.4 `openspec validate state-anchor-hook` PASS (final)

## 7. Commit + PR

- [x] 7.1 Commit SDD artifacts (`01b3dc8`)
- [x] 7.2 Commit RED tests (`fe2575b`)
- [x] 7.3 Commit GREEN impl + wire-up (`db40b61`)
- [x] 7.4 Push branch `state-anchor`, `gh pr create --base dev` -> PR #71 (https://github.com/amd2g2zz/kunglao-agent/pull/71)
- [x] 7.5 Do NOT merge; orchestrator verifies independently first (PR left OPEN)
