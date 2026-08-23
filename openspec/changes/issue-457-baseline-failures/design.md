# Design — 15 baseline failures: triage first, fix follows the class

Reproduction base: worktree branch `v012/issue-457-baseline-failures`
fast-forwarded to dev **97b4db1** (consumes #454's merge a0f6670; the issue's
original 15-item list was measured on dev 6462fe4).

## Triage table (conclusion first)

| # | Test | Root cause (verified on this machine) | Class | Fix |
|---|---|---|---|---|
| 1 | `test_acceptance.py::test_acceptance_overall_passes` | two-layer: (a) aggregates `test_suite_green` over the red suite (cascade); (b) on win32 `_test_suite_timeout_s` calls `os.getloadavg` — absent on Windows, raises **AttributeError** while the guard catches only OSError → every acceptance run fails with `error: module 'os' has no attribute 'getloadavg'` regardless of suite color | Cascade **plus** real product bug (platform guard catches wrong type) | widen the except to `(AttributeError, OSError)` (comment already declared that intent); cascade resolves with #2–#13 |
| 2 | `test_ghidra_async.py::TestCliErrors::test_help_exit_zero[start]` | `run_cli` decodes child output with locale (GBK) while `ghidra_job.py` emits UTF-8 (module-level reconfigure, line 64); argparse help carries an em-dash (UTF-8 `0x94`); reader thread `UnicodeDecodeError` → `stdout=None` → `'NoneType'.lower()` | Test non-closure (encoding) | `run_cli` subprocess: `encoding="utf-8", errors="replace"` (mirror `_tick`, test_heartbeat_tick.py:61) |
| 3 | same `[status]` | same | same | same |
| 4 | same `[cancel]` | same | same | same |
| 5 | same `[cleanup]` | same | same | same |
| 6 | `test_heartbeat_tick.py::TestRenewMarginLow::test_expired_state_still_warns` (and `test_low_margin_reported_and_printed`, same seam) | tick child prints the #365 warn line (em-dash, `RENEW_MARGIN_LOW_LINE`) to a pipe → encoded cp936; parent decodes UTF-8 (`_tick` already pins utf-8) → `\ufffd\ufffd`. `heartbeat_tick.py` lacks the repo #317 stdout guard | Real product bug (missing encoding guard) | main()-scoped `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` (mirror `scripts/mcp_probe.py`, import-safe) |
| 7 | `test_hook_registry_singlesource.py::test_wire_up_settings_exports_hook_deployment_targets` | resolver returns the CORRECT path (`D:\...\ws\.claude\settings.json`); the test asserts `str(ws_level).endswith("ws/.claude/settings.json")` — `str(Path)` yields native backslashes on win32. NOT machine-state dependent (issue hypothesis corrected) | Platform difference (test assertion) | compare `ws_level.as_posix().endswith(...)` — same exactness |
| 8 | `test_init_toolchain_gate.py::test_init_gate_resolves_platform_headless` | user-global mcp:ghidra registry leaked into the headless init run | Already owned | fixed by #454 (dev a0f6670, `KUNGLAO_CLAUDE_JSON` empty override); consumed via rebase. Zero diff here |
| 9 | `test_renderer_unify.py::test_golden_equivalence_byte_identical[windows]` | `write_claudemd` injects `str(SKILL_DIR)` → `\kunglao\skill-sentinel` on win32 vs golden `/kunglao/skill-sentinel`; exactly 10 sites × 2 separators = 20 diff chars, len equal. The path lands in **bash command lines** (`python <skill>/scripts/convergence_check.py .`) where backslashes are escapes — broken commands on win32, not just golden drift. (Python-version sentinel is already pinned by the test via `sys.version_info` monkeypatch — not part of the drift) | Real product bug | `"skill_dir": SKILL_DIR.as_posix()` in `kunglao-init.py` param construction (same rule as #367 hook stamping) |
| 10 | same `[linux]` | same mechanism (same param) | same | same |
| 11 | same `[android]` | same | same | same |
| 12 | `test_review_hook_install.py::test_installed_hook_with_placeholder_residue_fails_closed` | template's unstamped branch prints "REVIEW GATE BLOCKED: hook not installed — this is the tracked template" (em-dash → UTF-8 `0x94`); test's `sh` subprocess decodes locale (GBK) → reader thread crash → `stdout=None` → `None + str` TypeError at `out = r.stdout + r.stderr` | Test non-closure (encoding) | that subprocess: `encoding="utf-8", errors="replace"` |
| 13 | `test_review_hook_install.py::test_install_git_hooks_stamps_real_key_path` | final assertion `mode & stat.S_IXUSR` — `os.chmod` on win32 can only toggle the read-only flag; installed hook lands mode 0666. POSIX exec-bit semantics don't exist on NTFS via chmod | Platform difference (POSIX-only semantics) | extract the exec-bit assertion into a new dedicated test with `pytest.mark.skipif(os.name != "posix", reason=...)`; stamping/skill-root/uv assertions stay in the unskipped parent test |
| — | (not in the 15) `TestAsyncLifecycle::*` intermittent `state: 'failed'` | **Out-of-scope observation**: `poll_status` passes `--grace 0.2`; under concurrent machine load (parallel worktrees) the runner's first `runner_pid` report can lag > grace → `JobStore.detect_crash` ("runner never reported in", job_store.py:355) marks the job failed. Reproduced 3× under load, 0× quiet; passes 3/3 isolated. Not in issue #457's measured list (quiet machine) | Flake (load race) | NOT fixed here — RUNBOOK records it with a separate-issue recommendation (poll grace should exceed worst-case runner spawn, or poll_status should distinguish crash-failed from job-failed) |

Tally: 3 product bugs (#1b getloadavg guard, #6, #9–11) · 6 test
non-closure (#2–5, #12 — encoding seams) · 2 platform differences (#7, #13)
· 1 already owned (#8) · 1 cascade resolved by the rest (#1a) · 1
out-of-scope flake (documented).

## Appended scope (coordinator, 2026-08-18): runtime output mojibake

User-reported (NOT a test failure): `python scripts/convergence_check.py
<ws>` on a GBK console prints `??` for em-dash — same encoding family as
item #6, but the consumer is a human console, so the stdout-reconfigure guard
(which fixes UTF-8 readers) does not help a GBK console. Remedy per
coordinator: console-facing strings in convergence_check.py /
obligation_discovery.py / failure_analysis_gate.py become ASCII-only
(`—`→`->` or `-`, `§`→`S`, `→`→`->`); comments/docstrings untouched.
Tokenize-verified result: ZERO non-ASCII in non-docstring string literals of
all three files; repro on the user's workspace emits 278 bytes with 0
non-ASCII. No test pinned any affected string (grep-verified), so no
expectation changed — output side only, semantics untouched.

## Appended scope 2 (coordinator, second wave): hooks sweep + #454 live regression

1. **Live regression in merged dev (highest priority)**: #454's wired-but-
   dormant NOTE (`scripts/hook_activation.py:306`, mirrored in
   `scripts/kunglao-init.py:899`) contains an em-dash. Under
   `PYTHONIOENCODING=utf-8` + GBK console, `hooks_selfcheck.rebuild_project_level`'s
   `text=True` (locale/GBK) capture reader crashes on the child's UTF-8
   em-dash → `r.stdout=None` → `.strip()` AttributeError → report records
   `{"rebuilt": false, "error": "'NoneType' object has no attribute 'strip'"}`
   although settings.json WAS written, and the selfcheck exits 1.
   Reproduced red on this branch's base before the fix; fix = both NOTE
   strings ASCII (`dormant - activation is ...`); after: rc 0,
   `{"rebuilt": true, "rc": 0, ...}`. #454's own keyword assertions
   (`_assert_dormant_semantics`: wired/dormant/phase 0/ttl/--renew) do not
   pin the dash — all 50 wiring tests stayed green.
2. **hooks/ sweep (coordinator: "扩到 hooks/ 的输出字符串")**:
   worker_budget.py 52 output-string sites (REJECT deny reasons,
   additionalContext guidance: `heartbeat STALE (...) — cron not ticking` →
   ASCII `-`), worker_pulse.py 4, state_anchor.py 3 (⚠→`WARNING:`, …→`...`),
   dispatch_gate.py 2, completion_gate.py 2, env_check_gate.py 1,
   recall_inject.py 1. **Deliberately untouched**: matching patterns —
   worker_budget L245 regex (`don']?t`, curly-apostrophe U+2019), L741 BOM
   literal (U+FEFF), L847/L852 CJK keyword sets, recall_inject L68 CJK
   keyword list — these MATCH content, changing them breaks gate behavior.
   Tokenize+AST verified: zero non-ASCII in output strings of all hooks.
   One test pinned the ⚠ glyph (`test_state_anchor.py:152`) — updated in
   lockstep with the deliberate output change; 222 hook-family tests green.

## Design decisions

- **D1 — UTF-8 seams closed at the boundary that owns the decode.** The repo
  contract is "stdout unified on UTF-8" (#317). Tests that spawn CLI children
  must decode UTF-8 explicitly (`encoding="utf-8", errors="replace"`),
  mirroring the already-correct `_tick` helper. No expectation is ever bent
  toward mojibake: the child's bytes are correct; the reader was wrong.
- **D2 — heartbeat_tick guard is main()-scoped, not module-level.** The router
  imports `heartbeat_tick.main()` in-process (docstring, #370); a module-level
  reconfigure would mutate the importer's stdout at import time. Mirrors
  `scripts/mcp_probe.py` main-scoped guard with the same comment lineage.
- **D3 — platform skips are minimal-surface.** #13's skipif applies ONLY to
  the exec-bit assertion (its own test), not to the whole install happy-path;
  #7 needs no skip at all (as_posix is exact on both platforms).
- **D4 — golden fixtures are untouched.** The goldens encode the portable
  contract; the product was non-portable. `as_posix()` on the injected skill
  dir fixes rendered bash command lines on win32 — the golden equality is the
  proof, not the target.
- **D5 — no weakening.** No blanket skips, no relaxed assertions, no
  expectation edits. Every changed expectation string is the SAME string,
  compared through a separator-stable lens.

## Rejected

- **R1 — regenerate goldens on Windows.** Would bake backslash paths into
  fixtures and ship broken bash command lines. Violates the fixtures' own
  portability header.
- **R2 — skip the whole `test_install_git_hooks_stamps_real_key_path` on
  win32.** Loses ~30 lines of passing stamping coverage; the platform-limited
  surface is exactly one assertion.
- **R3 — patch `poll_status` grace in TestAsyncLifecycle.** Out of the issue's
  measured list; touching it risks masking a real runner-startup regression.
  Recorded for a separate issue instead.
- **R4 — fix #8 in-branch.** Diverges from #454's merged fix; rebasing to
  consume it is conflict-free by construction.
