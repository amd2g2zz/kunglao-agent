# Proposal: write_guard payload decode must never silently allow (#686)

## Problem

On Windows hosts (locale `cp936`/GBK), all 7 must-block contract tests of the
write_guard PreToolUse hook return `rc=0` with **empty stdout/stderr** — the
hook silently allows writes it is contractually required to block
(R1 self-stamp, W-2 invented status, unresolvable-workspace fail-closed,
block-must-emit-log, and the three #528 supersedes-chain shapes).
Linux CI is green, so the enforcement layer shipped believing it worked.

## Root cause (measured, 2026-08-25)

NOT the rule layer. In-process execution of the full decision flow
(`resolve_workspace` → `carrier_of` → `post_image` → `build_shadow` →
`adjudicate` legs `lint_facts` / `write_gate` / `notes_writer`) on Windows
produces the correct BLOCK verdict for every one of the 7 payloads.

The failure is one step earlier: `_read_payload()` reads stdin through the
text layer (`sys.stdin.read()`). The failing harnesses set
`PYTHONIOENCODING=utf-8` for the child while the parent
(`subprocess.run(..., text=True)`) encodes the payload JSON with the host
locale. Every failing payload carries a non-ASCII character (an em-dash
`—`, U+2014, in the fact/note bodies), which GBK encodes as `0xA1 0xAA` —
invalid UTF-8. The child's `sys.stdin.read()` raises `UnicodeDecodeError`;
`_read_payload`'s bare `except Exception` swallows it and returns `{}`;
`main()` then sees no `tool_input.file_path` and returns `RC_ALLOW` before
any carrier is ever resolved:

```
UnicodeDecodeError: 'utf-8' codec can't decode byte 0xa1 in position 1032: invalid start byte
```

(offset varies with path length; the trigger class is any non-ASCII byte
in a locale-encoded payload — verified: `locale.getpreferredencoding(False)
== 'cp936'` on the failing host; Linux hosts are utf-8 end-to-end so the
mismatch never fires there.)

So the issue's "adjudicate() rule-layer enforcement dead" narrows to:
**adjudication never runs** — the payload dies at the stdin decode gate and
the hook mistakes that for "not a file-writing tool call".

## Solution

1. `_read_payload()` reads **bytes** (`sys.stdin.buffer.read()`) and decodes
   through an explicit chain: `utf-8` (the Claude Code wire format) →
   `locale.getpreferredencoding(False)` (the locale-defaulting caller shape)
   → `utf-8` with `errors="replace"` (structure-preserving last resort).
   Decoding can no longer raise; the JSON parse follows.
2. A non-dict JSON payload degrades to `{}` instead of crashing `main()` with
   `AttributeError` (a list/scalar stdin was a latent rc=1 crash class).
3. `KUNGLAO_WG_DEBUG=1` trace channel: stderr lines at each `main()` decision
   point and per-leg counts inside `adjudicate()` — the diagnostic this
   investigation had to hand-roll as an out-of-tree driver.

## What does NOT change

- The R1 / W-2 / supersedes four-carrier semantics — untouched, and verified
  working in-process on Windows.
- The fail-closed posture on unadjudicable carrier writes.
- The allow contracts: non-carrier writes and schema-clean carrier writes
  still pass (pinned by allow-guard tests so a degenerate always-block fix
  cannot go green).

## Acceptance

- [ ] The 7 must-block payloads from the issue are green via the
      subprocess-stdin harness (end-to-end, not mock) — `tests/test_write_guard_686.py`.
- [ ] Allow guards: clean fact write (em-dash payload — pins the GBK-recovered
      allow path) and non-carrier write stay `rc=0`.
- [ ] `tests/test_write_guard_532.py` + `tests/test_write_guard_supersedes_528.py`
      go from 7 failed / 15 passed to 23/23 (no false-green flips).
- [ ] Root cause named with the reproducing byte class and the regression
      window (this file §Root cause + design.md D1).
- [ ] `KUNGLAO_WG_DEBUG=1` trace reproduces the decision flow on stderr.

## Out of scope

- Deleting the `tracked: #686` quarantine entries in
  `tests/v013_acceptance/conftest.py` — post-merge cleanup per the batch plan.
- Hardening the two harnesses to `encoding="utf-8"` — the production hook must
  survive locale-encoding callers; fixing only the tests would leave that hole.
