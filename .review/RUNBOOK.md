# RUNBOOK — issue #457: dev baseline 15 legacy test failures triage + fix

Branch: `v012/issue-457-baseline-failures` (worktree `D:/works/kunglao-wt/457`)
Base: dev **97b4db1** (fast-forward from 6462fe4 to consume #454's merge
a0f6670 — item #8's owner; zero diff contributed for it)
Process artifact per dev 97b4db1 convention (.review/ temp-only, gitignored).

## Triage table — 15 items, red → green evidence

| # | Test | Root cause | Class | Fix (commit) | Evidence (before → after) |
|---|---|---|---|---|---|
| 1 | `test_acceptance.py::test_acceptance_overall_passes` | two-layer: (a) cascade over the red suite; (b) win32 `os.getloadavg` missing raises **AttributeError**, guard caught only OSError → every acceptance run errored before even running the suite | cascade **+ real bug** | `aaf713b` (b); (a) resolved by #2–#13 | before: `acceptance failures: ['test_suite_green']` / detail `error: module 'os' has no attribute 'getloadavg'` → after: `{'passed': True, 'detail': '2119 passed, 6 skipped, 1 warning in 176.09s'}`; standalone `tests/test_acceptance.py`: `4 passed in 359.41s` |
| 2 | `test_ghidra_async.py::TestCliErrors::test_help_exit_zero[start]` | `run_cli` decoded child output with machine locale (GBK); `ghidra_job.py` emits UTF-8 (#317 module guard, L64); argparse help em-dash byte 0x94 crashed the capture reader thread → `stdout=None` → `'NoneType'.lower()` | 测试非封闭 (encoding) | `ad15e1d` — `encoding="utf-8", errors="replace"` in run_cli (mirrors `_tick`) | before: `AttributeError: 'NoneType' object has no attribute 'lower'` ×4 → after: `TestCliErrors` `11 passed` |
| 3 | same `[status]` | same | same | same | same |
| 4 | same `[cancel]` | same | same | same | same |
| 5 | same `[cleanup]` | same | same | same | same |
| 6 | `test_heartbeat_tick.py::TestRenewMarginLow::test_expired_state_still_warns` (+ `test_low_margin_reported_and_printed`, same seam) | tick child printed the #365 warn line (em-dash) to a pipe as cp936; parent `_tick` decodes UTF-8 → `\ufffd\ufffd`. `heartbeat_tick.py` lacked the repo stdout guard | 真实 bug (missing guard) | `8a2d034` — main()-scoped `sys.stdout.reconfigure(utf-8)` (mirrors `mcp_probe.py`, import-safe) | before: `assert '... 30-min TTL' in '... \ufffd\ufffd c...'` → after: file `6 passed` |
| 7 | `test_hook_registry_singlesource.py::test_wire_up_settings_exports_hook_deployment_targets` | resolver correct; test asserted `str(Path).endswith("ws/.claude/settings.json")` — win32 `str(Path)` is backslash-separated. Issue's "机器状态敏感" hypothesis corrected: pure separator diff | 平台差异 (test assertion) | `ebe2be1` — `as_posix().endswith(...)`, same exactness | before: `target[0] must resolve to the ws-level file: D:\works\kunglao-wt\457\ws\.claude\settings.json` → after: file `15 passed` |
| 8 | `test_init_toolchain_gate.py::test_init_gate_resolves_platform_headless` | user-global mcp:ghidra registry leaked into headless init | 已有归属 #454 | none — consumed via base rebase (dev a0f6670, `KUNGLAO_CLAUDE_JSON` isolation) | red on 6462fe4 (`ghidra check missing from report`) → green on 97b4db1 with zero local diff |
| 9 | `test_renderer_unify.py::test_golden_equivalence_byte_identical[windows]` | `write_claudemd` injected `str(SKILL_DIR)` → `\kunglao\skill-sentinel` on win32; exactly 10 sites × 2 separators = 20 diff chars, len equal (matches issue signature). Path lands in CLAUDE.md **bash command lines** (`python <skill>/scripts/convergence_check.py .`) where backslashes are escapes — broken commands on win32, not just drift. (Version sentinel already pinned by the test — not drift.) | 真实 bug | `0b9135a` — `SKILL_DIR.as_posix()` at param construction (same rule as #367 hook stamping); goldens untouched | before: `golden drift for windows: 20 first-diff chars; len 8684 vs 8684` ×3 → after: file `16 passed` |
| 10 | same `[linux]` | same | same | same | same |
| 11 | same `[android]` | same | same | same | same |
| 12 | `test_review_hook_install.py::test_installed_hook_with_placeholder_residue_fails_closed` | template's unstamped branch prints "hook not installed — this is the tracked template" (em-dash); test's `sh` subprocess decoded locale (GBK) → reader crash → `r.stdout=None` → `None + str` TypeError | 测试非封闭 (encoding) | `79398d7` — `encoding="utf-8", errors="replace"` | before: `TypeError: unsupported operand type(s) for +: 'NoneType' and 'str'` → after: file `8 passed, 1 skipped` |
| 13 | `test_review_hook_install.py::test_install_git_hooks_stamps_real_key_path` | final `mode & stat.S_IXUSR` — win32 `os.chmod` toggles read-only only; hook lands mode 0666. POSIX-only semantics | 平台差异 (POSIX exec bit) | `79398d7` — exec-bit assert extracted to `test_install_git_hooks_sets_exec_bit` with `skipif(os.name != "posix", reason=...)`; stamping/skill-root/uv assertions stay in the unskipped parent | before: `installed hook must be executable (mode 666)` → after: parent passes unskipped; skipped entry shows the reasoned skip line |

Tally: **3 real product bugs** (#1b, #6, #9–11) · **6 test non-closure** (#2–5, #12) ·
**2 platform differences** (#7, #13) · **1 already owned** (#8) · **1 cascade** (#1a).

## Appended scope (coordinator, 2026-08-18): runtime output mojibake — user-reported

`python scripts/convergence_check.py D:/works/samples/2026-07-01/malware-analysis-workspace`
printed `F028 <-> F029 ?? resolve ...` / `0/3 active ?? 3 free slot(s)` — em-dash/arrow
mojibake on GBK consoles. Same family as #6 but the consumer is a human console, so the
UTF-8 stdout guard (fixes UTF-8 readers) does not help; remedy per coordinator:
console-facing strings ASCII-only.

- `cb1f80a`: convergence_check.py 9 sites (`—`→`->`/`-`, `§`→`S`, `→`→`->`),
  failure_analysis_gate.py 11 sites; obligation_discovery.py had ZERO
  console-facing non-ASCII (both hits were docstrings). Comments/docstrings
  untouched (module docstring L22–25 of failure_analysis_gate keeps its glyphs).
- Verification: tokenize+AST scan — zero non-ASCII in non-docstring string
  literals of all three files; repro on the user workspace emits 278 bytes,
  **0 non-ASCII**, `workers: 0/3 active -> 3 free slot(s)` renders clean.
- No test pinned any affected string (grep across tests/) — output side only,
  semantics untouched.
- `3122f24`: F-12 golden (`expected/stdout.txt`, the only stdout-compared golden
  among F-01..F-12 — others assert exit code only) regenerated via the
  harness-equivalent replay; diff = exactly the 4 ASCII-fied guidance lines,
  rest byte-identical, pure-ASCII asserted. This is a golden following a
  deliberate output change, NOT an expectation bent toward mojibake.

## Final gate

```
uv run --project . python -m pytest -q -m "not load_sensitive"
→ 1969 passed, 6 skipped, 154 deselected, 1 warning in 511.39s (0:08:31)
```

**0 failed.** (154 deselected = load_sensitive, per #369 lock discipline; 6
skipped incl. the new reasoned POSIX-only exec-bit skip.)

## Overlap protection (#444 / #445) — merge-order notes

- **#444 (worker liveness) owns `convergence_check.py`**: my change there is 9
  string literals, line-local, zero logic. Merge order: either; if #444 lands
  first this branch rebases trivially (and vice versa).
- **#445 (hook wiring) owns hook_activation/wire_up/kicker**: NOT touched.
  `tests/test_hook_registry_singlesource.py` edits are assertion-lens only
  (`as_posix`), product resolvers untouched.
- `scripts/kunglao-init.py` (skill_dir as_posix) — #454 already merged into our
  base; no in-flight owner.
- No other kunglao-wt/* worktree was modified; nothing pushed; no PR opened.

## Out-of-scope observations (NOT in the 15; separate-issue recommendations)

1. **`TestAsyncLifecycle` load-race flake** (`test_ghidra_async.py`): `poll_status`
   polls with `--grace 0.2`; under concurrent machine load (parallel worktrees)
   the runner's first `runner_pid` report can lag the grace →
   `JobStore.detect_crash` ("runner never reported in", scripts/ghidra/job_store.py:355)
   marks the job `failed` → assertions see `'failed' != 'completed'`.
   Reproduced 3× under load, 0× quiet, 3/3 isolated passes, absent from the
   issue's measured list. Recommendation: poll grace should exceed worst-case
   runner spawn under load, or `poll_status` should distinguish
   crash-detected-failed from job-failed.
2. **win32 cannot sense load for the #369 timeout scaling**: `_test_suite_timeout_s`
   fail-opens to load=0.0 → always the 300s floor on Windows; on a busy
   multi-worktree machine the embedded acceptance suite can exceed it (observed
   once mid-fix; standalone re-run green in 176s). Operators can use the
   designed env override `KUNGLAO_TEST_SUITE_TIMEOUT` (>= 300). A win32
   CPU-queue heuristic would remove the residual flake class.
3. **`test_acceptance_overall_passes` flaky under concurrent pytest**:
   it runs the full suite as a subprocess while other pytest workers are active
   (5 parallel worktrees observed here). The embedded suite behaves correctly
   in isolation (2119 passed, 0 failed in 184s; confirmed 2× standalone).
   Concurrent runners cause ~1–4 non-deterministic failures in the embedded
   run. This is the #369 load-sensing gap on win32 applied to the acceptance
   itself — not a code defect in the fixes.

## Final gate

```
uv run --project . python -m pytest -q -m "not load_sensitive" tests/
→ 2119 passed, 6 skipped, 1 warning in 184.96s (0:03:04)  [single-process, isolated]

uv run --project . python -m pytest -q -m "not load_sensitive"
→ 1968 passed, 6 skipped, 154 deselected, 1 warning in 522–565s
  test_acceptance_overall_passes: flaky under concurrent worktree load
  (acceptance runs full suite as subprocess; concurrent pytest workers
   cause ~1–4 non-deterministic embedded failures; isolated: 4 passed/359s)
→ 0 failed in all isolated runs; the one intermittent red = documented
   #369 win32 gap in the acceptance's own subprocess harness.

openspec validate: same "valid: false — no deltas" as merged #454 precedent.
```

`openspec validate issue-457-baseline-failures` reports the same
`valid: false — no deltas` as the merged #454 precedent
(`openspec/changes/issue-454-quick-fixes`): test-repair changes in this repo
carry proposal/design/tasks without capability spec deltas. Mirrors precedent.
