# Baseline failures triage + fix — dev quick-gate 15 legacy reds (#457)

## Why

v0.1.2 milestone DoD requires "dev CI fully green". The clean dev baseline
quick gate (`uv run --project . python -m pytest -q -m "not load_sensitive"`)
measures **15 failed, 1951 passed, 5 skipped, 154 deselected** (2026-08-18,
issue #457 evidence). Every wave-0+ PR's lane gate subtracts signal from these
15 reds: a lane that goes 15→14 cannot tell its own regression from the
pre-existing baseline. This change removes the baseline noise **by root
cause**, never by weakening the tests.

## What Changes

Per-item triage (full table in `design.md`), repairs follow the
classification:

- **Encoding family (GBK console vs repo UTF-8 stdout contract, #317/#451/#434
  lineage)** — two test seams decode child output with the machine locale
  while the child emits UTF-8 (`tests/test_ghidra_async.py::run_cli`,
  `tests/test_review_hook_install.py` unstamped-template `sh` run): add
  `encoding="utf-8", errors="replace"` (mirrors the existing `_tick` helper
  in `tests/test_heartbeat_tick.py`). One product gap:
  `scripts/heartbeat_tick.py` prints the #365 warn line with an em-dash but
  lacks the repo-standard `sys.stdout.reconfigure(encoding="utf-8")` CLI
  guard — add it main()-scoped (mirrors `scripts/mcp_probe.py`, keeps import
  side-effect-free).
- **Platform differences (minimal, reasoned)** —
  `tests/test_hook_registry_singlesource.py` asserts `str(Path).endswith(...)`
  with hardcoded `/` separators: compare `as_posix()` (same exactness, no
  strength loss). `tests/test_review_hook_install.py` exec-bit assertion
  (`stat.S_IXUSR`) is unsettable on win32 (`os.chmod` toggles read-only only):
  extract into its own test with `skipif(os.name != "posix")`; the stamping
  coverage in the parent test stays unskipped.
- **Real product bug** — `scripts/kunglao-init.py::write_claudemd` injects
  `str(SKILL_DIR)` (native backslashes on win32) into CLAUDE.md **bash command
  lines** (`python \kunglao\...\scripts\convergence_check.py .` — backslashes
  are shell escapes), breaking both the golden portability contract
  ("deterministic across machines", tests/test_renderer_unify.py:45) and the
  rendered commands themselves on Windows. Emit `SKILL_DIR.as_posix()` (same
  rule the repo already applies to the #367 hook stamping).
- **Cascade** — `test_acceptance_overall_passes` aggregates `test_suite_green`;
  turns green when the rest are fixed. No separate change.
- **Already owned** — `test_init_toolchain_gate.py::test_init_gate_resolves_platform_headless`
  was fixed by #454 (merged dev a0f6670, `KUNGLAO_CLAUDE_JSON` registry
  isolation). This branch consumed it via rebase to dev 97b4db1; zero work
  here.

## Impact

- `tests/test_ghidra_async.py` (+2 kwargs), `tests/test_review_hook_install.py`
  (utf-8 decode + exec-bit test extraction), `tests/test_hook_registry_singlesource.py`
  (as_posix comparisons): test-side closure only.
- `scripts/heartbeat_tick.py` (+5 lines stdout guard), `scripts/kunglao-init.py`
  (1-line as_posix): minimal product fixes, files NOT owned by in-flight #444
  (worker liveness) / #445 (hook wiring) branches.
- NOT in scope: golden fixture regeneration (goldens are correct), the
  `TestAsyncLifecycle` load-race flake (not in the 15; recorded in RUNBOOK as
  a separate-issue recommendation), any blanket skip or assertion loosening.
