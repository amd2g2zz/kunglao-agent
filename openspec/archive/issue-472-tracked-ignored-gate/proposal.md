# Tracked-vs-ignored mechanical gate + .review legacy cleanup (#472)

## Why

dev HEAD contains two gitignored process artifacts tracked in the tree
(`.review/baseline-failures.txt`, `.review/final-failures.txt`, dragged in by
PR #460 squash f8119e8). This is the **third** incident of the same leak class
(#454's 97b4db1, #455's `.review/RUNBOOK.md` rebase collision).

Root cause is structural, not accidental: `.gitignore:73` has the `.review/`
rule and `tests/test_gitignore_coverage.py` only asserts the rule *text*
exists. gitignore prevents new untracked files from being added — it has **no
effect on files already in the index**, and nothing in CI cross-checks tracked
files against ignore rules. Worse, the natural cross-check is silently
defeated: `git check-ignore <path>` is index-aware and reports **exit 1 (not
ignored)** for tracked-but-ignored files. Only `--no-index` reveals the truth.

## What Changes

- **P1 — legacy cleanup**: `git rm --cached .review/baseline-failures.txt
  .review/final-failures.txt` (files stay on disk locally; they leave the
  tree). No test or script references them — pure process logs from PR #460.
- **P2 — mechanical gate**: new `tests/test_no_tracked_ignored_files.py`
  generalizes the `check-ignore` cross-validation paradigm of
  `tests/test_tools_structure_340.py:187` (tools/ subtree, `-q` probe) into a
  global invariant: every `git ls-files` entry is batch-fed to
  `git check-ignore --no-index --stdin`; any tracked-but-ignored path fails
  the test with the full offending list.
- **Allowlist (explicit, enumerated)**: full-repo scan on dev 8e85dfa finds
  exactly 4 legitimate tracked-but-ignored files — the golden fixtures
  `tests/fixtures/golden/F-03/ws/runs/worker-status-w{1,2,3}.md` and
  `tests/fixtures/golden/F-06/ws/runs/worker-status-w1.md`. They match the
  bare `runs/` rule (`.gitignore:32`, matched at any depth) but are
  load-bearing: `tests/test_suite_health.py::test_golden_replay` replays them
  byte-for-byte from `manifest.yaml`. They are listed in a
  `TRACKED_IGNORED_ALLOWLIST` constant with per-entry justification, and a
  companion assertion keeps the allowlist honest (stale entries fail the
  test). `.gitignore` itself is untouched — the rules are right; what was
  missing is enforcement.

## Impact

- New file `tests/test_no_tracked_ignored_files.py` (gate + allowlist).
- Index-only removal of the two `.review/*.txt` artifacts.
- Future leaks of the #454/#455/#472 class fail CI with a named file list
  instead of landing on dev unnoticed.
