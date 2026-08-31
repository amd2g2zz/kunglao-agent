## 1. Setup

- [x] 1.1 Worktree `D:/works/kunglao-wt/457` on `v012/issue-457-baseline-failures` off dev
- [x] 1.2 Rebase to dev 97b4db1 (consumes #454 for item #8) and re-measure the RED baseline on the new tip

## 2. SDD

- [x] 2.1 proposal.md (triage-first fix policy, references #457)
- [x] 2.2 design.md (15-item triage table: root cause / class / fix per item)
- [x] 2.3 tasks.md

## 3. Fixes (one commit per repaired group; RED evidence = this branch's baseline run)

- [x] 3.1 `tests/test_ghidra_async.py::run_cli` — utf-8 decode (items #2–#5)
- [x] 3.2 `scripts/heartbeat_tick.py` — main()-scoped stdout utf-8 guard (item #6)
- [x] 3.3 `tests/test_hook_registry_singlesource.py` — as_posix endswith (item #7)
- [x] 3.4 `scripts/kunglao-init.py` — `SKILL_DIR.as_posix()` into CLAUDE.md params (items #9–#11)
- [x] 3.5 `tests/test_review_hook_install.py` — utf-8 decode (item #12) + exec-bit test extraction with reasoned skipif (item #13)
- [x] 3.6 `scripts/acceptance_check.py` — `_test_suite_timeout_s` catches AttributeError (win32 lacks os.getloadavg; item #1's win32 root cause beyond the cascade)
- [x] 3.7 items #8 (owned by #454, consumed via dev rebase) and #1 cascade — no diff, verify only
- [x] 3.8 Appended (coordinator): convergence_check.py + failure_analysis_gate.py console-facing strings ASCII-only (9 + 11 sites; obligation_discovery.py had none); tokenize-verified; user-workspace repro 0 non-ASCII bytes
- [x] 3.9 Appended wave 2: #454 dormant-NOTE em-dash live regression (hook_activation.py:306 + kunglao-init.py:899) — rebuilt:false/'NoneType.strip' under PYTHONIOENCODING=utf-8 reproduced and fixed
- [x] 3.10 Appended wave 2: hooks/ output-string sweep (worker_budget 52 + worker_pulse 4 + state_anchor 3 + dispatch_gate 2 + completion_gate 2 + env_check_gate 1 + recall_inject 1); matching regexes/keyword lists/BOM untouched; test_state_anchor ⚠ pin updated in lockstep

## 4. Validation

- [x] 4.1 Per-fix: affected file goes red→green (`uv run --project . python -m pytest -q -m "not load_sensitive" <file>`)
- [ ] 4.2 Final quick gate: `uv run --project . python -m pytest -q -m "not load_sensitive"` → 0 failed
- [ ] 4.3 `openspec validate issue-457-baseline-failures` PASS
- [ ] 4.4 RUNBOOK: triage table with red→green evidence + gate tail line
