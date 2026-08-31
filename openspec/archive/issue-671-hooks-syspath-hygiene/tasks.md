## 1. Setup

- [x] 1.1 Worktree branch `issue-671-hooks-syspath-hygiene` off origin/dev `2b7f946` (#719 head)
- [x] 1.2 Baseline census: `grep -rn "sys\.path\.insert" hooks/` → **31 sites / 13 files** (issue body: 11; dispatch sweep: 32; wide-regex variant: 31 — actual wins)

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 proposal.md (three-basis count table + hygiene-module rationale vs #684 per-site by-path)
- [x] 2.2 design.md (D1 membership semantics, D2 site classification 20/10/1, D3 bootstrap argument, D4 guard, D5 #684 relation, D6 RED/GREEN)
- [x] 2.3 specs/hooks-syspath-hygiene/spec.md
- [x] 2.4 tasks.md
- [x] 2.5 `npx openspec validate issue-671-hooks-syspath-hygiene` exit 0

## 3. RED — guard + semantic pins

- [x] 3.1 `tests/test_syspath_hygiene_671.py`: scanner (bare `sys.path.insert` in hooks/, whitelist `_path_hygiene.py`) + planted-violation negative sample + sys.path-unchanged pin (real entry `completion_gate._kunglao_active`) + ensure idempotence/anti-flip pin + front move-to-front pin
- [x] 3.2 RED run recorded: guard reports 31 (full site list in failure message); 9 pins error on missing module, 3 scanner self-tests green — `1 failed, 3 passed, 9 errors`

## 4. GREEN — module + 31-site migration

- [x] 4.1 `hooks/_path_hygiene.py`: `on_path` / `scripts_on_path` / `ensure_on_path(front=)` / `ensure_scripts_path`
- [x] 4.2 dispatch_gate cluster (9: lines 93/142/176/211/341/362/442/473/479) → scoped `with`
- [x] 4.3 completion_gate:73, state_anchor:126, worker_pulse:71/135/233, orchestrator_tool_guard:57, env_check_gate:155, lib_kunglao:308 → scoped `with`
- [x] 4.4 worker_budget_gates:96/221 → scoped `with`
- [x] 4.5 module-level cluster → `ensure_*`: env_check_gate:54, lib_kunglao:248, recall_inject:74, session_start:20, state_anchor:68, worker_budget_core:42/75/100/118, write_guard:52/53
- [x] 4.6 worker_budget.py:20 → `ensure_on_path(_HERE, front=True)` (#568-faithful)
- [x] 4.7 `release-manifest.yaml`: declare `hooks/_path_hygiene.py`
- [x] 4.8 Guard green (31 -> 0 bare inserts outside whitelist) + 13/13 pins green, incl. end-to-end completion_gate pin
- [x] 4.8a D3-amendment: scripts-side by-path exec of hooks/lib_kunglao.py (8 _load_worker_lib consumers, no hooks/ on subprocess sys.path) broke on the new top-level import — fixed by by-path self-bootstrap fallback in lib_kunglao.py (and, found at full-suite time, dispatch_gate.py for the tmp-driver pattern); 4 real regressions (dlq / W-15 / resume / trajectory_replay) reproduced, fixed, green; base 2b7f946 confirmed clean on all 4
- [x] 4.9 Existing-suite regression batch (842 passed; gate_power_473 fault-injection = pre-existing red on base, verified by stash): test_hook* / test_wire_up* / test_gate* / test_worker_budget* / test_completion* / test_dispatch* / test_state_anchor* / test_worker_pulse* / test_env_check* / test_no_absolute_paths
- [x] 4.10 Full suite vs dev baseline ledger (Gate 2 known-red: probe_tiers×2 only)

## 5. Gates

- [x] 5.1 `uv run python devkit/quality_gates.py` — Gates 1/3/4/5/6/7 PASS, Gate 2 PASS (exit 0); full-suite own run: failopen_emit driver regression found + fixed (by-path-without-path set = {lib_kunglao, dispatch_gate}, both self-bootstrap), final failures all stash-proven base-red: probe_tiers×2 (host ledger) + gate_power_473 + init_deploy_env + v012_milestone×2

## 6. Commits (mint-gated — stage, report sha, STOP for mint, commit after confirm)

- [ ] 6.1 C1: openspec four-piece set
- [ ] 6.2 C2: RED guard test (tests-only)
- [ ] 6.3 C3: GREEN — `hooks/_path_hygiene.py` + 13-file migration + release-manifest entry

## 7. Reporting (orchestrator-owned actions beyond this card)

- [ ] 7.1 Issue #671 comment: 11 (filed) vs 32 (dispatch) vs 31 (actual @2b7f946) reconciliation — after C3 confirm
- [ ] 7.2 Push + PR left to orchestrator
