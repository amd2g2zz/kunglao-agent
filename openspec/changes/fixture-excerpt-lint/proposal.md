# Proposal — fixture condensed-excerpt conversion ban (#58)

## Why

The a2b5e25c problem-1 root cause lived in a worker's CONDENSED Ghidra decompile
excerpt (`fixtures/a2b5e25c/decomp/nvenc_create_d3d11_encoder.c`). The excerpt
introduced an UNANNOTATED semantic conversion:

```c
init.frameRateNum = bitrate; init.frameRateDen = fps;
rc.averageBitRate = bitrate*1000; rc.maxBitRate = bitrate*1000; rc.gopLength = fps;
```

The `*1000` (kbps→bps unit conversion) has NO machine-code basis — zero
imul/shl/0x3E8 across the function's 349/358 instructions (Ghidra body and
capstone, two counting bases). The report's code-listing 10 copied the excerpt
verbatim, so a customer audit found 5 assignments mismatching the binary
(frameRateNum=fps not bitrate; Den=1 not fps; avg=max=bitrate not bitrate*1000;
gopLength=0xFFFFFFFF not fps). Experiment exp-A2 (H-A') showed the FAITHFUL
decompile introduces conversion/scaling ASSUMPTIONS only at the COMMENT layer;
the worker materialized the assumption into code (`*1000`) with no annotation.

The condensed-excerpt layer therefore needs a front-line mechanical rule:

1. No UNANNOTATED semantic conversion (unit conversion, scaling, symbolic
   assumption); any conversion MUST carry a `unit:` caliber annotation (same
   source as `~/.claude/rules/common/numeric-fidelity.md`).
2. Assignments/constants in excerpts MUST be traceable to raw disasm (address +
   bytes) — enforced structurally by #50's VA anchoring; #58 does not duplicate.
3. Unresolved variables (`sVar1`/`sVar5`) MUST NOT be speculatively assigned —
   mark `// resolved: <how>` or resolve-then-reference (resolution is a #49
   prerequisite).

The two existing mechanical checkers do NOT cover the excerpt-authoring layer:

- **#50 disasm_constant_check** is BYTE-EXACT and needs the sample binary + a
  VA anchor on each assertion; its `scaled` kind disproves a `*1000` only by
  scanning disasm for an imul/1000 at the VA. It runs AFTER the excerpt is
  VA-anchored, against the binary. It does not read the excerpt text in
  isolation and cannot run at fixture-authoring time without the binary.
- **#49 fact-expected-value-binding** binds a fact's `expected:` values for
  cross-layer comparison; it does not lint the excerpt's internal arithmetic.

Neither catches "this condensed `.c` excerpt contains an unannotated `*1000`"
at authoring time, without the binary. #58 is that missing front-line layer.

## What Changes

- **`scripts/fixture_excerpt_lint.py`** (new, pure stdlib):
  - `lint(excerpt_text) -> dict`: scans a condensed `.c` excerpt for two smell
    rules and returns a dict (`ok`, `violation_count`, `violations`, `checks`).
    - **R1 unannotated-conversion**: an assignment whose RHS contains a
      numeric-literal scaling operator (`*N`, `<<K`, `/N`, `>>K` with a numeric
      operand; `//` and `/*` comment starts are excluded so comments are not
      parsed as division) is FLAGGED unless a `unit:` caliber annotation is in
      scope. A scaling by a known unit-conversion constant
      (1000/1024/100/8/60/3600/0x3E8/...) is reported at `severity="high"`; any
      other numeric scaling at `severity="normal"`. Variable-only arithmetic
      (`a * b`) is NOT flagged (no numeric operand).
    - **R3 unresolved-speculation**: an assignment whose LHS is a generic
      Ghidra unresolved name (`sVarN`/`uVarN`/`lVarN`/`unaff_*`) is FLAGGED when
      the RHS contains a "concrete or semantic" element (a numeric literal, or
      an identifier that is NOT itself a generic name / cast type keyword),
      unless a `// resolved: <how>` annotation is on the line. A faithful
      temp-to-temp copy (`sVar1 = sVar2;`) or a cast of a generic
      (`sVar1 = (long)sVar2;`) is NOT flagged.
  - `unit:` exemption: (a) the literal `unit:` substring on the assignment's
    physical line, OR (b) a preceding `// unit:` declaration line within the
    same fenced block (before the next blank line).
  - `main()` CLI: `python scripts/fixture_excerpt_lint.py <excerpt.c>` → JSON
    report. Exit 0 = clean, 1 = ≥1 violation, 2 = unreadable file.
- **`tests/test_fixture_excerpt_lint.py`** (new, RED first): (a) the nvenc
  regression excerpt (issue #58 body, verbatim) → the two `*1000` statements
  flagged (R1, high severity); (b) the SAME excerpt with a
  `// unit: bps (kbps*1000)` annotation → 0 violations; (c) `sVar1 = bitrate;`
  flagged (R3), the same with `// resolved:` → 0, and `sVar1 = sVar2;` → 0
  (faithful); (d) a clean faithful excerpt → 0 violations (precision guard);
  (e) variable-only multiply → 0; (f) CLI exit 0/1/2; (g) module docstring names
  #50 and #49.
- **`references/excerpt-lint.md`** (new): the rule in prose (the three rules,
  the `unit:` / `resolved:` annotation contracts, the layering vs #50/#49), so
  the rule survives change-archive. Does NOT edit any existing failure-modes-*
  file (those are #56's surface).

## Non-goals

- NOT a byte-exact checker — #50 is. #58 reads the excerpt TEXT only; it never
  opens the binary, never resolves a VA, never runs capstone. It cannot prove a
  conversion wrong against disasm; it flags the ABSENCE OF AN ANNOTATION.
- NOT an expected-value binder — #49 is. #58 does not compare the excerpt to a
  fact's `expected:` map.
- NOT a structural traceability enforcer — Rule 2 (every assignment traceable
  to address+bytes) is enforced by #50's VA-anchoring contract, not re-implemented
  here. #58 cross-references Rule 2 in docs only.
- NOT semantic — regex heuristics only, no LLM. The recall/precision tradeoff
  is documented in design.md (D5).
- Does NOT modify malware-veri-notes (cross-skill); the malware-veri-notes
  fixture spec MAY reference/invoke this lint later (noted as follow-up in the
  PR body).

## Capabilities

### Added Capabilities

- `fixture-excerpt-lint`: condensed-excerpt-TEXT lint flagging unannotated
  semantic conversions (`*N` without `unit:`) and unresolved-variable
  speculation (`sVarN = <concrete>` without `// resolved:`); complementary to
  #50 (byte-exact, binary+VA) and #49 (expected-value binding).

## Impact

- `scripts/fixture_excerpt_lint.py`: new, ~240 lines (R1 + R3 detectors,
  `unit:`/`resolved:` exemption, CLI).
- `tests/test_fixture_excerpt_lint.py`: new, ~220 lines (~11 tests).
- `references/excerpt-lint.md`: new, the rule in prose.
- Suite impact (baseline at fd53d93): `scripts/` 226 passed → 226 unchanged
  (lint is tests/-exercised); `tests/` 350 passed + 1 skipped + 6 pre-existing
  failures → +N new passes, the SAME 6 pre-existing failures unchanged.
- Related: #50 (disasm_constant_check — byte-exact, cross-ref not duplicate),
  #49 (fact-expected-value-binding — cross-ref not duplicate), malware-veri-notes
  fixture spec (future consumer, cross-skill, out of scope here).
