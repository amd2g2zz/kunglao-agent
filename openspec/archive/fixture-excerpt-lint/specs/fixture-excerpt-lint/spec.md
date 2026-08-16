## ADDED Requirements

### Requirement: lint SHALL flag unannotated semantic conversions with severity

`lint(excerpt_text: str) -> dict` SHALL scan a condensed C decompile excerpt
for assignment statements and flag any assignment whose RHS (code part,
comments stripped) contains a numeric-literal scaling operator — multiply
(`*<num>`), divide (`/<num>`, excluding `//` and `/*` comment starts),
shift-left (`<< <num>`), or shift-right (`>> <num>`) — when no `unit:` caliber
annotation is in scope. The function signature SHALL be
`lint(excerpt_text: str) -> dict`. The returned dict SHALL carry keys `ok`
(bool, True iff `violation_count == 0`), `violation_count` (int), `violations`
(list of per-violation dicts each carrying `rule` (`"R1"` or `"R3"`),
`severity` (`"high"` for a known unit-scale operand on R1, else `"normal"`; R3
violations are `severity="normal"`), `line_no` (int, the physical line),
`snippet` (the offending statement, trimmed), `operand` (the matched
operator+number string for R1, else `None`), and `note` (str)), and `checks`
(int, the number of assignment statements scanned). The lint SHALL use regex
heuristics ONLY (no LLM, no binary, no network).

A scaling operand that parses (decimal or 0x-hex) to a member of
`KNOWN_UNIT_SCALES` {1000, 0x3E8, 1024, 0x400, 1000000, 0x100000, 100, 8, 60,
3600, 512, 2048, 4096} SHALL be reported at `severity="high"`; any other
numeric scaling SHALL be reported at `severity="normal"`. Variable-only
arithmetic with no numeric operand (e.g. `a * b`) SHALL NOT be flagged.

#### Scenario: nvenc regression — *1000 without unit: is flagged (R1 high)
- **GIVEN** the excerpt is the issue #58 body's quoted nvenc excerpt containing `rc.averageBitRate = bitrate*1000;` and `rc.maxBitRate = bitrate*1000;` and no `unit:` annotation
- **WHEN** `lint(excerpt)` is called
- **THEN** `ok` is False, at least two R1 violations are present, every R1 violation on those statements has `severity="high"` and `operand` containing `1000`, and the averageBitRate / maxBitRate statements appear in `violations`

#### Scenario: variable-only multiply is not flagged
- **GIVEN** an excerpt containing `x = a * b;`
- **WHEN** `lint(excerpt)` is called
- **THEN** `ok` is True and `violation_count` is 0

#### Scenario: known unit-scale vs other numeric scaling severities
- **GIVEN** an excerpt containing `a = n * 1000;` and `b = m * 4;` (no annotations)
- **WHEN** `lint(excerpt)` is called
- **THEN** both statements are flagged R1; the `*1000` violation has `severity="high"` and the `*4` violation has `severity="normal"`

### Requirement: lint SHALL flag unresolved-variable speculation unless // resolved:

`lint` SHALL flag an assignment whose LHS (token before the first `=`) is a
generic Ghidra unresolved name (matching `^[a-zA-Z]Var\d+$` or `^unaff_\w+$`)
when the RHS contains a numeric literal OR an identifier that is NOT a generic
Ghidra name (`[a-zA-Z]Var\d+`, `unaff_\w+`, `FUN_[0-9a-fA-F]+`, `param_\d+`,
`in_\w+`, `out_\w+`) and NOT a C cast type keyword (the `TYPE_KEYWORDS` set
`long/int/short/char/_DWORD/_QWORD/...`). Such a violation SHALL have
`rule="R3"` and `severity="normal"`. The statement SHALL NOT be flagged when
its physical line carries a `// resolved:` annotation (the literal substring
`resolved:` on the line), NOR when the RHS is composed solely of generic names,
cast keywords, and operators (a faithful temp-to-temp copy or cast).

#### Scenario: sVar assigned a semantic name is flagged (R3)
- **GIVEN** an excerpt containing `sVar1 = bitrate;` with no `resolved:` annotation
- **WHEN** `lint(excerpt)` is called
- **THEN** an R3 violation is present on that line with `rule="R3"`

#### Scenario: resolved annotation exempts R3
- **GIVEN** an excerpt containing `sVar1 = bitrate; // resolved: reg-tracked from EBX at 0x401234`
- **WHEN** `lint(excerpt)` is called
- **THEN** no R3 violation is present on that line

#### Scenario: faithful temp copy and cast are not flagged
- **GIVEN** an excerpt containing `sVar1 = sVar2;` and `sVar3 = (long)sVar4;`
- **WHEN** `lint(excerpt)` is called
- **THEN** no R3 violation is present

### Requirement: unit: annotation SHALL exempt R1 (same-line or block-scoped)

A conversion SHALL be exempt from R1 when EITHER (a) the assignment's physical
line contains the literal substring `unit:`, OR (b) a preceding line within the
same fenced code block — before the next blank line — matches a unit-declaration
comment (`^\s*(?://|#|/\*)\s*unit:\s*\S`).

#### Scenario: same-line unit: exempts the *1000
- **GIVEN** the nvenc regression excerpt with a trailing `// unit: bps (kbps*1000)` annotation on the line carrying the `*1000` statements
- **WHEN** `lint(excerpt)` is called
- **THEN** `ok` is True and `violation_count` is 0

#### Scenario: block-scoped unit declaration exempts a block
- **GIVEN** an excerpt with `// unit: all rates in bps` on its own line immediately followed (no blank line) by `rc.averageBitRate = bitrate*1000;`
- **WHEN** `lint(excerpt)` is called
- **THEN** the `*1000` statement is NOT flagged

### Requirement: a clean faithful excerpt SHALL yield zero violations

`lint` SHALL return `ok=True, violation_count=0` for a clean condensed excerpt
that contains only raw field assignments and constant copies — no numeric-literal
scaling and no unresolved-LHS speculation. This is the precision regression guard.

#### Scenario: clean faithful excerpt is zero-violation
- **GIVEN** an excerpt containing only `init.frameRateNum = fps; init.frameRateDen = 1; rc.gopLength = 0xFFFFFFFF;` (no scaling, no sVar)
- **WHEN** `lint(excerpt)` is called
- **THEN** `ok` is True and `violation_count` is 0

### Requirement: the CLI SHALL read an excerpt file and emit JSON with exit 0/1/2

`scripts/fixture_excerpt_lint.py::main()` SHALL accept a positional
`<excerpt.c>` (UTF-8 text), run `lint`, and print the return dict serialized as
JSON (`ensure_ascii=False`, `indent=2`) to stdout. It SHALL exit 0 when
`violation_count == 0`, 1 when `violation_count >= 1`, and 2 when the excerpt
file cannot be read (clear error to stderr).

#### Scenario: CLI clean excerpt exits 0
- **GIVEN** a UTF-8 file containing a clean excerpt
- **WHEN** `python scripts/fixture_excerpt_lint.py <file>` runs
- **THEN** stdout is valid JSON with `ok` True and the exit code is 0

#### Scenario: CLI violating excerpt exits 1
- **GIVEN** a UTF-8 file containing the nvenc regression excerpt
- **WHEN** `python scripts/fixture_excerpt_lint.py <file>` runs
- **THEN** stdout is valid JSON with `ok` False and at least one R1 violation, and the exit code is 1

#### Scenario: CLI missing file exits 2
- **GIVEN** a path that does not exist
- **WHEN** `python scripts/fixture_excerpt_lint.py <missing>` runs
- **THEN** a clear error is printed to stderr and the exit code is 2

### Requirement: the module SHALL cross-reference #50 and #49 as complementary, non-duplicate layers

The module docstring of `scripts/fixture_excerpt_lint.py` SHALL name both `#50`
(byte-exact disasm-constant checker, binary+VA required) and `#49` (fact
expected-value binding) and state that #58 is COMPLEMENTARY (excerpt-TEXT,
authoring-time, no binary), not a duplicate of either. The reference doc
`references/excerpt-lint.md` SHALL carry the same cross-reference.

#### Scenario: module docstring names #50 and #49
- **WHEN** the module docstring of `fixture_excerpt_lint` is read
- **THEN** it contains the literal `#50` and the literal `#49`
