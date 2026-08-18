# REVIEW — issue #454 quick fixes (v012/issue-454-quick-fixes)

- Reviewer: independent subagent (maker-checker; implementer ≠ reviewer)
- Scope reviewed: `D:/works/kunglao-wt/454`, branch `v012/issue-454-quick-fixes` (base `dev` @ 6462fe4), commits 986c145 / 931ac75 / 11cea41 / 2a2e174 / ed9d354 / bc0aa27
- Inputs: issue #454 (amd2g2zz/kunglao-agent), `.review/RUNBOOK.md`, plan `v0-1-2-milestone-execution.plan.md` (Task 3 + Patterns to Mirror), `git diff dev..HEAD`

## 总评: **PASS**

6/6 checklist items pass; 0 FAIL items. 4 minor observations recorded at the
bottom (documentation/reproducibility level, none block merge).

---

## 1. RED 真实性 — PASS

**RED-a (931ac75)**

```
$ git checkout 931ac75
$ uv run --project . python -m pytest -q -m "not load_sensitive" \
    tests/test_init_toolchain_gate.py::test_platform_headless_isolated_from_user_global_ghidra_registration
FAILED ... AssertionError: ghidra check missing from report: [...
  CheckResult(name='decompiler', status=PASS, detail='via MCP (ghidra)', ...),
  CheckResult(name='mcp:ghidra', status=PASS, detail='registered (user-global)', ...)]
1 failed in 0.17s
```

Fails at the RED commit with the *exact* issue assertion (issue #454 §1),
including `mcp:ghidra registered (user-global)` proving the hostile injected
registry drove the MCP-first short-circuit. Matches RUNBOOK line 18-20
("reproduced the exact issue assertion"). Deterministic on any machine — no
real machine state needed (verified: `toolchain.py:302-308` only checks
registry *presence* via `mcp_probe.registered_names`, no live connection).

**RED-b (2a2e174)**

```
$ git checkout 2a2e174
$ uv run --project . python -m pytest -q -m "not load_sensitive" tests/test_issue454_wiring_transparency.py
FAILED ...::test_wire_up_output_says_wired_but_dormant -
  AssertionError: wired-but-DORMANT state not stated: OK: kunglao-agent hooks wired into ...
FAILED ...::test_init_hooks_output_says_wired_but_dormant -
  AssertionError: wiring line missing: ... kunglao-init: hooks -> ... (2 entries, idempotent)
2 failed in 1.57s
```

Both surfaces red exactly as RUNBOOK line 20 describes ("failed on
dormant/wired semantics missing at both surfaces"). Worktree restored to
branch head `bc0aa27` afterwards (verified, clean status).

## 2. checkbox ↔ 测试映射 — PASS (2/2)

| #454 acceptance checkbox | Test (file :: function) |
|---|---|
| 该测试在"全局注册 mcp:ghidra"的机器上通过(隔离注入) | `tests/test_init_toolchain_gate.py::test_init_gate_resolves_platform_headless` (isolation injected, GREEN-a) + `tests/test_init_toolchain_gate.py::test_platform_headless_isolated_from_user_global_ghidra_registration` (regression, simulates the hostile machine deterministically) |
| init 输出含 hook 激活语义说明(wired ≠ active) | `tests/test_issue454_wiring_transparency.py::test_init_hooks_output_says_wired_but_dormant` (init surface) + `::test_wire_up_output_says_wired_but_dormant` (bonus --wire-up surface) |

No missing mapping. Both target tests pass at HEAD (part of the domain run
below). Note the isolation fix lives in the *test* as the issue itself
prescribes ("修复方向:测试内隔离 MCP 注册表来源") — not evasion.

## 3. Pattern 忠实度(计划 Patterns to Mirror)— PASS

- **NAMING** — branch `v012/issue-454-quick-fixes` ✓; commits `<type>: <desc> (#454)` ✓ (`test: RED ...`, `fix: ...`); test file name `test_issue454_wiring_transparency.py` follows repo precedent of issue-numbered test files (`test_dedup_319.py`, `test_fix_98_deadlock.py`). 986c145 uses `sdd(issue-454):` — type-with-scope form, consistent with repo history `fix(#99):` / `feat(skill):` (see observation O-2).
- **SEAM** — the isolation uses the *documented* env seam, not monkeypatched internals: `scripts/mcp_probe.py:135-140` `claude_json_path()` — `"""(KUNGLAO_CLAUDE_JSON override for tests)"""`. Faithful to the `_subprocess_run`-style "test injection point" philosophy.
- **FAIL_CLOSED** — not applicable to a print-only change; no error handling added or removed anywhere in the diff.
- **并发锁 (#369)** — all gates run with `-m "not load_sensitive"`; new tests are not load_sensitive-marked, consistent with sibling hook tests (`test_wire_up_settings.py`, `test_heartbeat_off.py` carry no marker either).
- **风格不可区分性** — `tests/test_issue454_wiring_transparency.py` mirrors `tests/test_heartbeat_off.py` structurally: `ROOT`/`SCRIPTS` module constants, `_run_*` helper wrapping `subprocess.run([sys.executable, ...], capture_output=True, timeout=120)` with `PYTHONIOENCODING=utf-8`, issue-anchored docstrings/comments. Product comments (`# #454: wiring != activation ...`) match the repo's `# <issue>: <why>` comment idiom.
- **Copy accuracy** — the dormant line states exactly what `hooks/dispatch_gate.py:54-63` implements: no `.hook_state.json` → sleep, orchestrator Phase 0 activation, 30-min TTL renewed by `--renew`. TTL interpolated from the single source (`scripts/hook_activation.py:68 DEFAULT_TTL_MINUTES = 30`); `kunglao-init.py` imports it (`from hook_activation import DEFAULT_TTL_MINUTES as HOOK_TTL_MINUTES`) — no second hardcoded 30 anywhere in the new code.

## 4. GREEN 最小性 — PASS

- **11cea41 (GREEN-a)**: 10 added lines, `tests/test_init_toolchain_gate.py` ONLY, zero product code (verified via `git show --stat` + full diff: the isolation block inside the existing test). Issue's fix direction mandates test-side isolation, so test-only GREEN is correct here.
- **ed9d354 (GREEN-b)**: 19 added lines across exactly 2 files — `scripts/hook_activation.py` (+8: 3 comment + 5-line print in the `--wire-up` branch) and `scripts/kunglao-init.py` (+11: 3-line import + 4 comment + 5-line print in the hooks-deployed branch). Output lines + single-source TTL interpolation only. No scope creep: `hooks/dispatch_gate.py` untouched, no #445 self-check added, no behavior change (prints only), diff stat total for branch = 9 files (4 openspec + RUNBOOK + 2 scripts + 2 tests).

## 5. 门禁复现 — PASS(域门数字除外,见 O-1)

**Repo quick gate** (worktree, `-m "not load_sensitive"`):

```
13 failed, 1956 passed, 5 skipped, 154 deselected, 6 warnings in 215.12s
```

**Exact match** with RUNBOOK line 61 (1956 passed / 5 skipped / 154
deselected / 13 failed). The 13 distribute exactly as RUNBOOK line 65-69
claims: acceptance 1 (`test_acceptance_overall_passes`, cascade of
`test_suite_green`), ghidra_async 4 (`test_help_exit_zero[...]` × 4,
`AttributeError: 'NoneType' ... .lower'`), heartbeat_tick 2
(`test_low_margin_reported_and_printed` + `test_expired_state_still_warns`,
em-dash encoding), hook_registry_singlesource 1 (ws-path), renderer_unify 3
(golden drift), review_hook_install 2 (exec-bit/NoneType). 1+4+2+1+3+2 = 13 ✓.

**Domain gate** (change-surface superset: init_toolchain_gate, kunglao_init,
toolchain, toolchain_install, wire_up_settings, heartbeat_off,
issue454_wiring_transparency):

```
127 passed, 1 skipped in 68.27s
```

Green with exactly 1 skip; the skip is a *pre-existing* conditional skip in
files #454 does not touch (`tests/test_toolchain.py:432/627` "port 23946
busy" / `tests/test_kunglao_init.py:87`). RUNBOOK's "86 passed, 1 skipped"
count could not be reproduced bit-exactly because the RUNBOOK does not record
the exact domain file list — see O-1.

## 6. RUNBOOK 诚实性(13 失败全存量抽查)— PASS

Two failure files re-run on the clean baseline worktree
`D:/works/kunglao-agent-dev` @ 6462fe4 (`uv run --frozen`, worktree left
unmodified apart from its pre-existing dirty `uv.lock`):

- `tests/test_ghidra_async.py` — the same 4 `test_help_exit_zero[*]`
  NoneType failures, test-for-test identical to the 454 worktree.
- `tests/test_hook_registry_singlesource.py::test_wire_up_settings_exports_hook_deployment_targets`
  — same assertion, same shape, worktree-path-parameterized only
  (`D:\works\kunglao-agent-dev\ws\.claude\settings.json` vs
  `D:\works\kunglao-wt\454\ws\...`), confirming RUNBOOK risk #4 (machine/
  path-state-sensitive pre-existing failure).

Both sampled failure sets pre-exist on the pre-change baseline → RUNBOOK's
"13 failures all pre-existing" conclusion is honest. See O-3 for one
baseline-only flake observed during spot-check.

---

## Observations(非 FAIL,不阻塞 merge)

- **O-1 (LOW, docs)**: RUNBOOK cites the domain quick gate as "86 passed, 1
  skipped" but does not record the exact file list, so the number is not
  machine-reproducible (a plausible 7-file superset gives 127 passed / 1
  skipped, green). Substance (green + exactly 1 pre-existing skip) verified.
  Suggest future RUNBOOKs paste the literal pytest command line.
- **O-2 (LOW)**: 986c145 is the first `sdd(<issue>):` commit in repo history;
  fits the existing `type(scope):` shape but is first-of-kind — fine as a
  v0.1.2 lane convention.
- **O-3 (LOW, pre-existing flake)**: on the clean dev baseline standalone,
  `tests/test_ghidra_async.py::TestAsyncLifecycle::test_cancel_active_job_then_cancel_is_noop`
  failed once (async JSON-timing compare) while passing in both the 454 full
  gate and the 454 standalone run. Fails on the *pre-change* baseline, hence
  cannot be #454-caused; flag for a flakiness sweep later, out of #454 scope.
- **O-4 (LOW, SDD shape)**: `openspec/changes/issue-454-quick-fixes/` has
  proposal/design/tasks (+`.openspec.yaml`) but no `specs/` subdir, unlike the
  mirrored `openspec/archive/external-kicker/`. RUNBOOK's "mirror of
  external-kicker shape" is very slightly overstated; immaterial.

## Verdict

**PASS** — proceed to Task 4 (fault injection) / PR. No FAIL items.
