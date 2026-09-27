# Excerpt lint — condensed decompile excerpt rules (#58)

The condensed decompile excerpt layer (`fixtures/<sample>/decomp/*.c`) carries a
front-line mechanical lint: `scripts/fixture_excerpt_lint.py`. It enforces the
three rules below at **authoring time, on the excerpt TEXT** — before any binary
is involved, before any VA anchor or expected-value binding exists. The rule set
is the a2b5e25c problem-1 postmortem (a worker materialized `rc.averageBitRate =
bitrate*1000;` — a kbps→bps conversion with zero machine-code basis and no
`unit:` note — into a condensed excerpt that the report copied verbatim).

## The three rules

1. **No unannotated semantic conversion.** An assignment whose RHS contains a
   numeric-literal scaling operator (`*N`, `/N`, `<<K`, `>>K`) MUST carry a
   `unit:` caliber annotation. Variable-only arithmetic (`a * b`) is exempt —
   the smell is a bare numeric scale factor, the shape of a unit conversion.
2. **Assignments/constants MUST be traceable to raw disasm** (address + bytes).
   This is enforced structurally by #50's VA anchoring (`parse_assertions`,
   `require_va=True`) and byte-exact disasm comparison; the excerpt lint
   cross-references it but does not re-check VA presence.
3. **No unresolved-variable speculation.** An assignment whose LHS is a generic
   Ghidra unresolved name (`sVarN`, `uVarN`, `lVarN`, `unaff_*`) MUST NOT bind
   to a concrete/semantic value unless the line carries a `// resolved: <how>`
   annotation. Keep the variable unresolved (`sVar1 = sVar2;`), or
   resolve-then-reference with the annotation (resolution itself is a #49
   prerequisite — the lint checks the annotation, not the resolution's correctness).

## Annotation contracts

- **`unit: <caliber>`** — exempts Rule 1. Two forms:
  - **same-line** — `rc.averageBitRate = bitrate*1000; // unit: bps (kbps*1000)`
  - **block-scoped declaration** — a comment-only line `// unit: all rates in bps`
    immediately above a block of assignments (no blank line between) exempts Rule
    1 for the whole block. A blank line ends the block.
  This is the excerpt-layer enforcement of
  `~/.claude/rules/common/numeric-fidelity.md` (a numeric fact must carry its
  caliber; a conversion must carry its unit).
- **`// resolved: <how>`** — exempts Rule 3 (same-line). `<how>` should name the
  resolution evidence, e.g. `// resolved: reg-tracked from EBX at 0x401234`.

## CLI

```
python scripts/fixture_excerpt_lint.py <excerpt.c>
```

JSON report `{ok, violation_count, violations:[{rule, severity, line_no,
snippet, operand, note}], checks}`. Exit 0 clean / 1 ≥1 violation / 2 unreadable
file. A scaling operand in `KNOWN_UNIT_SCALES` (1000/1024/100/8/60/3600/...) is
`severity=high`; any other numeric scaling is `severity=normal`.

## Layering — complementary, not duplicate

| Layer | Tool | Input | Catches |
|---|---|---|---|
| Excerpt-TEXT (front-line, this) | `scripts/fixture_excerpt_lint.py` (#58) | raw `.c` text, no binary | unannotated `*1000` / speculated `sVarN` at authoring time |
| Byte-exact (back-line) | `tools/static/disasm_constant_check.py` (#50) | sample PE + VA-anchored assertions + capstone | a `*1000` claim with NO imul/<K> at the VA (disasm disproves the multiply) |
| Expected-value | fact-expected-value-binding (#49) | a fact's `expected:` value map | report listing diverging from the fact's bound expected values |

#50 and #58 both flag the a2b5e25c `*1000` — by design, at different layers:
#50 disproves the multiply at the VA in disasm (needs the binary); #58 smells the
unannotated scaling op in the text (needs only text). Defense in depth. The lint
is heuristic (regex only, no LLM); its precision/recall stance is documented in
`openspec/changes/fixture-excerpt-lint/design.md` (D5): fires loudly on the
documented `*1000` failure, quietly on clean faithful excerpts.

## Detection notes (honest limits)

- **Recall gap**: a conversion phrased without a bare numeric operand (e.g.
  `x = y << 3 + y << 1` for `*10`, or `#define K 1000; x = y * K;`) is NOT
  caught. The operator tables are module constants, extensible for new patterns.
- **Precision stance**: a faithful `len = count * 4;` (struct stride) DOES flag
  Rule 1 — the release valve is the `unit:` annotation (e.g.
  `// unit: sizeof(int) stride`), exactly the traceability note a condensed
  excerpt should carry.
- Compound assignments (`x += 1`, `x *= 1000`) and conversions inside call
  arguments (`foo(b * 1000)`) are not scanned; the rule's scope is the
  assignment statement. Multi-line `/* ... */` block comments are tracked;
  string literals containing `//` are not (condensed excerpts rarely carry such
  strings).

## Related

- `~/.claude/rules/common/numeric-fidelity.md` — the `unit:` caliber rule (this
  lint is its excerpt-layer enforcement).
- `tools/static/disasm_constant_check.py` (#50) — byte-exact checker (back-line).
- fact-expected-value-binding (#49) — expected-value binding.
- `openspec/changes/fixture-excerpt-lint/` — full SDD (proposal/design/spec/tasks).
- malware-veri-notes fixture spec — may reference/invoke this lint in a future
  cross-skill change (follow-up; not modified by #58).
