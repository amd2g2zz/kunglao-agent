# Design: no-absolute-paths guard + test purge (#690)

## D1 — Detection regex

```
DRIVE = re.compile(r"[A-Z]:/|[A-Z]:\\(?![nrt])")
```

Design constraints discovered during the audit (each backed by a real line
in the pre-fix tree):

| Candidate | Outcome | Why |
|---|---|---|
| `[A-Za-z]:[\\/]` + lookbehind `(?<![A-Za-z0-9])` | rejected | lookbehind hides real sites where the drive letter follows an escape (`"\r\nC:\\vms-tmp..."` — test_env_manifest.py:656 was missed); still flags `a:\n` code text |
| `[A-Za-z]:[\\/]` no lookbehind | rejected | flags `a:\n` (test_toolchain.py:97), `\d\d:` regex classes (test_suite_health.py:159-160), `https://` |
| `[A-Z]:[\\/]` no lookbehind | rejected | flags uppercase identifiers before escape text: `PENDING:\n`, `JSON:\n` (test_mechanisms_retirement.py:202,217; test_v012_milestone_audit.py:166) |
| `[A-Z]:/ \|[A-Z]:\\(?![nrt])` | **chosen** | forward slash is never an escape → always a hit; backslash form excludes only the common escape letters n/r/t; doubled `\\` (escaped backslash) still hits (`"C:\\vms"` raw source = `C:` `\` `\` → second `\` is not n/r/t) |

Uppercase-only matches the existing house guard lineage
(`test_skill_contract.py:27` HARDCODED `[A-Z]:[\\/]`). Known blind spot,
documented in the guard docstring: a raw single-backslash path whose first
segment starts with n/r/t (`X:\temp`) — no such shape exists in this tree;
the sentinel mechanism covers it if one ever lands.

## D2 — Whitelist (three categories, nothing else)

1. **Guard self-scan** — the guard scans `tests/` including its own file;
   its regex source and sentinel list are written so they cannot match
   themselves (verified by the guard passing on its own source). Negative
   sample content is built by concatenation of inert fragments, never a
   literal.
2. **Platform-independent sentinels** — `SENTINELS = ("/dev/null",
   "/dev/stdin", "/dev/stdout", "/dev/stderr")`. Inert for D1 (no
   letter+colon), kept as an explicit, tested category so future pattern
   extensions (POSIX absolute paths) inherit the carve-out.
3. **`HISTORICAL-PATH-EXAMPLE` line sentinel** — any line containing this
   token is skipped. Works both as a trailing comment and inside docstring
   text (a docstring line cannot carry a `#` comment, so the token is
   matched anywhere in the line). Reserved for docstring/comment prose that
   cites a concrete historical incident (the #356/#367 `<HOME>/...`
   references in test_hardcode_purge.py and test_review_hook_install.py).
   Generic drive enumerations in prose are reworded instead of marked
   (e.g. `no absolute paths (C:\\, D:\\, ...)` → `(Windows drive roots,
   ...)`). The sentinel is pinned by its own tests: sentinel+drive →
   skipped; drive without sentinel → flagged.

## D3 — Transform catalog (per site class)

| Class | Rule | Example |
|---|---|---|
| Absolute path used AS a path | `tmp_path`-derived | `ghidra_home=str(tmp_path / "ghidra")` |
| Assertion mirrors an input | derive from the input variable, no second literal | `assert rp.analyze_headless_path(home) == expected` with `expected = (Path(home)/"support"/"analyzeHeadless.bat")` |
| Pure string shape (inert value) | relative form | `f"python hooks/{h}"`, `"output_dir=work/p1/stages"` |
| Active detection needle / parser fixture that must carry a drive shape | concatenation of inert fragments | `"<DRIVE>:" "<HOME>/"`, `b"C:" + b"\\proj\\synthetic.pdb"`, `_PROJECT_KEY = "<DRIVE>:" + "/some/ws"` |
| Docstring/comment citing an incident | keep verbatim + `HISTORICAL-PATH-EXAMPLE` | see D2.3 |
| Docstring/comment generic enumeration | reword | see D2.3 |
| Legacy compat constants (must stay byte-exact) | concat preserves the value | `OLD_PY = "C:" + r"\Users\hr\AppData\..."` |
| Skipped stub with env fallback default | drop the literal default, skip when env unset | `ghidra_home = os.environ.get("GHIDRA_HOME")` + skip guard |

Module-level fixtures that need an absolute shape use
`tempfile.gettempdir()` derivation (same spirit as `tmp_path`; module scope
has no fixture).

## D4 — Cross-guard safety

- `test_hardcode_purge.py` ALLOWLIST mentions `test_suite_health.py`
  (functional rebase constants) — those constants keep byte-exact values
  via concatenation, so the allowlist entry stays truthful.
- The purge edits inside `test_hardcode_purge.py` add only the sentinel
  token to already-allowed docstring lines; its own
  `C:[/\\]+Users[/\\]+[a-z]` scan is unaffected (file self-allowlisted).
- `test_skill_contract.py` is untouched.

## D5 — RED/GREEN protocol

The guard lands in the same commit as the openspec artifacts (commit 1,
tests-only) while the 112 sites are still present → guard is RED at that
commit, mechanically reproducible by `git checkout <c1> && pytest
tests/test_no_absolute_paths.py`. Clusters land in commits 2–3; the PR head
is GREEN. The negative-sample test proves the guard can fail independent of
the live tree.
