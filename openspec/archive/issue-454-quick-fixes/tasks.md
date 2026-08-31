## 1. Setup

- [x] 1.1 Branch `v012/issue-454-quick-fixes` off `dev` baseline 6462fe4,
      worktree D:/works/kunglao-wt/454 (one issue / one branch / one worktree)
- [x] 1.2 Read the plan (v0-1-2-milestone-execution) + issue #454 body

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 proposal.md (why: false-red test on global-mcp:ghidra machines +
      "wired" output reads as armed while hooks are TTL-dormant)
- [x] 2.2 design.md (D1 KUNGLAO_CLAUDE_JSON seam + R1/R2 rejected;
      D2 dormant line vocabulary + R3/R4 rejected)
- [x] 2.3 tasks.md

## 3. RED a — test isolation

- [x] 3.1 `test_platform_headless_isolated_from_user_global_ghidra_registration`
      (injects a hostile user-global mcp:ghidra registry via
      KUNGLAO_CLAUDE_JSON, calls the platform-headless test as a function)
- [x] 3.2 Confirm RED: pytest the file — the new test FAILS (MCP-first
      short-circuits, independent ghidra item missing)

## 4. GREEN a — isolation injection

- [x] 4.1 `test_init_gate_resolves_platform_headless` sets
      KUNGLAO_CLAUDE_JSON → empty `{}` registry (inner override beats the
      outer hostile one)
- [x] 4.2 Confirm both the target test and 3.1 are green; no product code
      touched

## 5. RED b — wiring ≠ activation transparency

- [x] 5.1 `tests/test_issue454_wiring_transparency.py`:
      `test_wire_up_output_says_wired_but_dormant` (subprocess
      hook_activation.py --wire-up) + `test_init_hooks_output_says_wired_but_dormant`
      (subprocess kunglao-init.py --skip-toolchain --hooks-json)
- [x] 5.2 Confirm RED: both FAIL (no dormant semantics in output)

## 6. GREEN b — dormant line at both surfaces

- [x] 6.1 `scripts/hook_activation.py` --wire-up: NOTE line (dormant /
      Phase 0 / DEFAULT_TTL_MINUTES-min TTL / --renew)
- [x] 6.2 `scripts/kunglao-init.py` hooks-deployed branch: same vocabulary
      line, TTL via `from hook_activation import DEFAULT_TTL_MINUTES`

## 7. Validation

- [x] 7.1 Quick gate: `uv run --project . python -m pytest -q -m "not load_sensitive"` → green
- [x] 7.2 `.review/RUNBOOK.md` written (changes / test map / risks)

## 8. Commits

- [x] 8.1 `sdd(issue-454): ...` — openspec artifacts
- [x] 8.2 `test: RED ...` + `fix: ...` — isolation pair
- [x] 8.3 `test: RED ...` + `fix: ...` — transparency pair
- [x] 8.4 `docs: RUNBOOK` — review handoff
