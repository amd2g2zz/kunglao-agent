# Proposal: purge hardcoded absolute paths from tests (#690)

## Problem

User policy (verbatim, 2026-08-25): "肯定不能写绝对路径，只能写相对路径。"

`tests/` carries 112 hardcoded drive-letter absolute-path sites across 23
files (audit 2026-08-25 on dev `b2b3661`, regex `[A-Z]:/|[A-Z]:\\(?![nrt])`).
The issue's original count (78 sites / 26 files) predates the #681–#685
merges; the re-audit on the current base is what this change targets.
Heavy files: `test_env_manifest.py` (15), `test_ghidra_tools.py` (15),
`test_toolchain_next_action.py` (10), `test_bindiff.py` (9),
`test_env_check.py` (9).

Typical shape (`tests/test_bindiff.py:143`):
`build_bindiff_command(ghidra_home="D:/ghidra", ...)` plus a second literal
in the assertion (`assert cmd[0] == "D:/ghidra/support/analyzeHeadless.bat"`).
These are synthetic values that pass on this host but:

1. are all Windows-drive shaped — cross-platform assertions need
   `.replace("\\", "/")` patches;
2. form a double standard with the real-path guards (`test_hardcode_purge.py`,
   `test_skill_contract.py` HARDCODED regex) — those catch real user paths
   while synthetic absolute paths sail through;
3. teach every copy-paste contributor the wrong idiom.

## Solution

Two moves, per the issue body:

1. **Transform all 112 sites** (move values, do not delete tests):
   - absolute path shape needed → derive from `tmp_path`
     (`ghidra_home=str(tmp_path / "ghidra")`);
   - assertions derive the expected value from the input variable — no
     second literal;
   - pure string shapes → relative path or `os.sep` construction;
   - active detection needles and parser fixtures that legitimately carry a
     drive shape → built by concatenation of inert fragments
     (`"<DRIVE>:" + "/<HOME>/"`, `b"C:" + b"\\proj\\..."`);
   - docstrings/comments citing historical incidents (e.g. the #356/#367
     `<HOME>/...` references) stay verbatim, marked with the
     `HISTORICAL-PATH-EXAMPLE` line sentinel;
   - generic drive enumerations in prose get reworded, not marked.
2. **New guard** `tests/test_no_absolute_paths.py`: recursive source scan of
   `tests/**/*.py` with the drive-letter regex; whitelist limited to the
   guard's own mechanics (self-scan), platform-independent sentinels
   (`/dev/null` class), and the historical-example sentinel. Negative-sample
   self-test plants a violating file in `tmp_path` and asserts the scanner
   flags it (the guard must be provably capable of going red).

## Out of scope

- Real-path guards (`test_hardcode_purge.py`, `test_skill_contract.py`) —
  their allowlists and regexes are untouched (values they compare against
  are preserved byte-exact where functional).
- Non-test trees (scripts/, tools/, hooks/) — already covered by
  test_hardcode_purge's whole-tree scan.
- Windows-IP literals (192.168.20.x) — different pattern class, not #690.

## What changes

- 23 test files under `tests/` (the audit list; every site moved, zero
  assertions deleted).
- NEW `tests/test_no_absolute_paths.py` (guard + negative sample).
- `openspec/changes/issue-690-no-absolute-paths/` SDD artifacts.

## Acceptance

- [ ] Audit scan of `tests/`: 112 → 0 sites outside the whitelist.
- [ ] Guard test RED against the pre-fix tree (reproducible at the RED
      commit), GREEN at PR head; negative sample proves the guard flags
      planted violations.
- [ ] Full-suite pass rate does not drop vs. the dev baseline ledger
      (values moved, tests not deleted).

## Related

- #356 W3 (hardcode purge), #367 (review-key path) — historical incidents
  cited by the kept docstrings.
- #689 suite speedup — the guard runs in seconds (source scan only).
