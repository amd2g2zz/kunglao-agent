## 1. Setup

- [x] 1.1 Worktree `D:/codebase/kunglao-issue-690-no-absolute-paths` branch `issue-690-no-absolute-paths` off origin/dev `b2b3661`
- [x] 1.2 Baseline audit: 112 sites / 23 files (regex `[A-Z]:/|[A-Z]:\\(?![nrt])`; issue's 78/26 was pre-#681-#685)

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 proposal.md (policy quote + re-audit numbers)
- [x] 2.2 design.md (D1 regex table, D2 whitelist, D3 transform catalog, D4 cross-guard safety, D5 RED/GREEN)
- [x] 2.3 specs/no-absolute-paths/spec.md
- [x] 2.4 tasks.md

## 3. RED — guard test

- [x] 3.1 `tests/test_no_absolute_paths.py`: scanner + main assertion (RED: 112 sites) + negative sample + sentinel pins + escape pins
- [x] 3.2 Run against pre-fix tree, record RED output (site count in failure message)

## 4. GREEN — cluster purge (112 → 0, values moved not deleted)

- [x] 4.1 Ghidra cluster: test_bindiff.py(9), test_ghidra_tools.py(15), test_ghidra_async.py(4) — tmp_path derivation + needle concat + skip-stub env guard
- [x] 4.2 toolchain+env cluster: test_env_manifest.py(15), test_toolchain_next_action.py(10), test_env_check.py(9), test_toolchain_negotiation.py(3), test_mcp_supply.py(3), test_pkg_detect.py(2), test_orchestration_hardening.py(2), test_template_gen.py(8), test_external_kicker.py(5), test_wire_up_settings.py(1)
- [x] 4.3 rest: test_hardcode_purge.py(6 sentinel), test_suite_health.py(4), test_review_hook_install.py(3), test_static_tools_1c.py(3), test_ext_index.py(3), test_normalize_trace.py(2), test_rust_dep_strings.py(2), test_icd203_alignment.py(1), test_state_anchor.py(1), test_yara_tools.py(1)
- [x] 4.4 Per-cluster target-file pytest runs
- [ ] 4.5 Full suite `uv run python -m pytest tests/ -q --durations=5` — no failures outside the dev baseline ledger

## 5. Gates

- [ ] 5.1 `uv run python devkit/quality_gates.py` — all 7 (Gate 2 per baseline ledger)

## 6. Commits (mint-gated, stop and report before each)

- [ ] 6.1 C1: openspec artifacts + RED guard (tests-only commit)
- [ ] 6.2 C2: Ghidra cluster GREEN
- [ ] 6.3 C3: toolchain+env + rest GREEN (guard green)
- [ ] 6.4 Push via Git Data API + PR `fix(#690): purge hardcoded absolute paths from tests — tmp_path/relative only + guard test` (Closes #690)
