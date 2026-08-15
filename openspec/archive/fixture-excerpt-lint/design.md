# Design — fixture condensed-excerpt conversion ban (#58)

## Design Decisions

### D1. Layering: excerpt-TEXT (authoring-time) vs byte-exact (#50) vs expected-value (#49)

#58 operates at a distinct layer from the two existing mechanical checkers:

| Layer | Issue | When it runs | What it reads | Catches |
|---|---|---|---|---|
| Byte-exact | #50 | after VA-anchoring, against the binary | sample PE + VA-anchored assertions + capstone disasm | a `*1000` claim with NO imul/1000 at the VA (disasm disproves the multiply) |
| Expected-value | #49 | fact/report cross-layer | a fact's `expected:` value map | report listing diverging from the fact's bound expected values |
| Excerpt-TEXT (THIS) | #58 | at fixture authoring, on the `.c` text | the excerpt TEXT only | an unannotated `*1000` in the excerpt (the SCALING OP has no `unit:` note) |

#50 and #49 both consume STRUCTURED, ANCHORED inputs (a binary + VAs, or an
expected-value map). Neither reads a raw condensed `.c` excerpt in isolation.
The a2b5e25c failure shows the gap: the `*1000` was baked into the excerpt
BEFORE any VA anchor or expected-value binding existed, and the excerpt was
later copied into the report verbatim. #58 reads the excerpt text precisely
because the smell lives there, at authoring time, before the binary is involved.

This is why #58 MUST NOT duplicate `check_fact_disasm` (#50) or
`parse_expected_map` (#49): it consumes a different input (raw excerpt text, no
binary, no VAs, no expected map) at a different time (authoring, before
byte-verification). See R1, R2.

Both #50 and #58 DO flag the a2b5e25c `*1000` — by design, at different layers:
#50 disproves the multiply at the VA in disasm (needs binary); #58 smells the
scaling op without a `unit:` note (needs only text). Defense in depth.

### D2. Conversion detection: numeric-literal scaling, conversion-vs-arithmetic

The calibration target is `rc.averageBitRate = bitrate*1000;`. The smell is a
SCALING OPERATOR WITH A NUMERIC OPERAND on an assignment RHS:

| Pattern | Regex core | Example | Flag |
|---|---|---|---|
| multiply by literal | `\*\s*(?:0x[0-9a-fA-F]+\|\d+)` | `bitrate*1000` | yes |
| divide by literal | `/(?![*/])\s*(?:0x[0-9a-fA-F]+\|\d+)` | `total / 1024` | yes |
| shift left | `<<\s*(?:0x[0-9a-fA-F]+\|\d+)` | `addr << 12` | yes |
| shift right | `>>\s*(?:0x[0-9a-fA-F]+\|\d+)` | `flags >> 1` | yes |
| variable-only arithmetic | (none of the above) | `a * b`, `x + y` | NO |

The conversion-vs-arithmetic line is drawn at the NUMERIC OPERAND. `a * b`
(two variables) is normal computation and is NOT flagged — there is no unit
literal to annotate. `a * 1000` introduces a numeric scale factor and IS
flagged; the author either annotates (`// unit: ...`) or removes the invented
multiply. This is deliberately conservative on the scaling dimension: in a
CONDENSED excerpt the analyst transcribes raw disasm, and a bare numeric scale
factor on an assignment is exactly the smell that produced the a2b5e25c
mismatch.

`severity` discriminates textbook unit conversions from other scaling:
- `high` — the operand parses to a member of `KNOWN_UNIT_SCALES` {1000, 0x3E8,
  1024, 0x400, 0x100000, 1000000, 100, 8, 60, 3600, 512, 2048, 4096} (kbps→bps,
  KiB↔byte, byte↔bit, minute/hour, etc.).
- `normal` — any other numeric scaling (e.g. `*4`, `<<3`). Still flagged (exit 1);
  the `unit:` annotation is the release valve.

Both severities contribute to `violation_count` and exit 1. The a2b5e25c
`*1000` is `severity=high` (1000 ∈ KNOWN_UNIT_SCALES).

### D3. `unit:` exemption syntax

A conversion is ANNOTATED (exempt from R1) iff:

(a) **same-line** — the assignment's physical line contains the literal substring
`unit:` (typically a trailing `// unit: bps (kbps*1000)`); OR
(b) **block-scoped declaration** — a preceding line within the same fenced
code block matches a unit-declaration comment
(`^\s*(?://|#|/\*)\s*unit:\s*\S`, i.e. a comment whose first token after the
marker is `unit:`), and no blank line separates the declaration from the
assignment.

Form (a) is the precise, line-local exemption (the regression test (b) uses
it). Form (b) lets an author place a single `// unit: all rates in bps` header
above a block of rate assignments; the block scope (blank-line reset) prevents
a declaration from over-exempting unrelated code later in the excerpt. This
mirrors the `unit:` caliber rule in
`~/.claude/rules/common/numeric-fidelity.md` (a numeric fact must carry its
caliber; a conversion must carry its unit) — #58 is the excerpt-layer
enforcement of that rule.

### D4. Unresolved-variable speculation: the identifier discriminator

The smell (issue rule 3, experiment exp-A2): a worker keeps a generic Ghidra
unresolved name on the LHS (`sVar1`, `uVar2`, `lVar5`, `unaff_EAX`) but binds
it to a CONCRETE or SEMANTIC value — asserting "I know what sVar1 holds" —
without a `// resolved: <how>` note.

Discriminator:
- LHS (token before the first `=`) matches `^[a-zA-Z]Var\d+$` (covers
  sVar/uVar/iVar/lVar/pVar/bVar/dVar/fVar/wVar/...) or `^unaff_\w+$`.
- The RHS (code part, comment and trailing `;` stripped) is inspected for
  identifiers (`[A-Za-z_]\w*`) and numeric literals.
- An identifier is GENERIC (does NOT trigger speculation) if it matches a
  Ghidra generic pattern (`[a-zA-Z]Var\d+`, `unaff_\w+`, `FUN_[0-9a-fA-F]+`,
  `param_\d+`, `in_\w+`, `out_\w+`) OR is a C cast type keyword
  (`long/int/short/char/_DWORD/_QWORD/...` in `TYPE_KEYWORDS`).
- Speculation fires if the RHS contains a numeric literal OR any non-generic
  identifier.

Worked examples:

| Line | RHS tokens | Speculation? | Why |
|---|---|---|---|
| `sVar1 = sVar2;` | sVar2 (generic) | NO | faithful temp-to-temp copy |
| `sVar1 = (long)sVar2;` | long (type), sVar2 (generic) | NO | faithful cast of generic |
| `sVar1 = bitrate;` | bitrate (semantic) | YES | asserts sVar1 = a named value |
| `sVar1 = 0x100;` | literal | YES | asserts a concrete value |
| `sVar1 = param_1->count;` | param_1 (generic), count (semantic) | YES | asserts a field source |
| `sVar1 = sVar2 + sVar3;` | sVar2, sVar3 (generic) | NO | faithful arithmetic on temps |
| `sVar1 = bitrate; // resolved: reg-tracked from EBX at 0x401234` | bitrate | NO | annotated |

The `// resolved:` exemption is same-line (the literal substring `resolved:` on
the assignment's physical line). Resolution itself (proving sVar1 = bitrate) is
a #49 prerequisite — #58 only checks that a resolution CLAIM is annotated, not
that it is correct.

### D5. Heuristic, not semantic — documented precision/recall stance

The lint uses regex only. It does NOT call an LLM, does NOT open the binary,
does NOT resolve VAs. The tradeoff:

- **Precision risk (false positive)**: a faithful excerpt that legitimately
  contains `len = count * 4;` (struct stride) or arithmetic on an unresolved
  temp with a literal would flag R1 (the `*4`) / R3 (the literal). The release
  valve is the `unit:` / `resolved:` annotation — exactly the traceability note
  a condensed excerpt should carry anyway. The clean-faithful-excerpt test (d)
  is the regression guard that a genuinely clean excerpt (no scaling, no
  speculated sVar) stays at 0.
- **Recall risk (false negative)**: a conversion phrased without a bare numeric
  operand (`bitrate_kbytes << 3 + bitrate_kbytes << 1` for `*10`, or a macro
  `#define K 1000; x = y * K;`) is NOT caught. Mitigation: the operator
  patterns are table-driven module constants (extensible). Acceptance #2
  requires only that the a2b5e25c `*1000` is flagged (the regression case),
  not every conceivable phrasing.

Stance: prefer a lint that fires loudly on the documented failure (the `*1000`)
and quietly on clean faithful excerpts (0 on the clean fixture), with the
annotation/operator tables extensible.

### D6. Pure stdlib, importable + CLI-runnable

No third-party imports (no capstone, no pefile — those are #50's deps). `lint()`
is the importable entry; `main()` is the CLI. The JSON report shape mirrors
#50's for familiarity: `{ok, violation_count, violations:[{rule, severity,
line_no, snippet, operand, note}], checks}`. `checks` = the number of
assignment statements scanned (the denominator for the lint's coverage).

## Rejected alternatives

### R1 (rejected): reuse #50's byte-exact checker instead of a text lint

Rejected: #50 needs the sample binary + a VA anchor on each assertion. At
fixture-authoring time the condensed `.c` excerpt has NEITHER — it is plain
text. Running #50 would require importing the binary, VA-anchoring every line,
and only THEN discovering the `*1000`. #58 runs on the `.c` text alone, at
authoring time, before any of that. Different input, different layer, different
time. #50 and #58 are complementary (D1): #50 disproves the multiply at the VA;
#58 smells the unannotated scaling op. Both catch a2b5e25c — defense in depth.

### R2 (rejected): enforce Rule 2 (traceability to address+bytes) mechanically here

Rejected: "every assignment traceable to raw disasm (address + bytes)" is a
STRUCTURAL contract enforced by #50's VA-anchoring (`parse_assertions`,
`require_va=True`) and byte-exact disasm comparison. Re-implementing it in #58
would duplicate #50. #58 cross-references Rule 2 in `references/excerpt-lint.md`
but does not check VA presence; its mechanical scope is Rules 1 (conversion)
and 3 (speculation) — the two smells #50 does not cover at the text layer.

### R3 (rejected): LLM-based semantic detection

Rejected: a regex lint is deterministic, fast, offline, and CI-runnable; an
LLM call would add cost, latency, and non-determinism to a gate that must give
the same answer on the same excerpt. The recall gap vs an LLM is real (D5) but
bounded by table-driven operator/exemption patterns. Same stance as #54 R3.
