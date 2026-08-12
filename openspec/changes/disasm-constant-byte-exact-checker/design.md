# Design — disasm-constant-byte-exact-checker (#50)

## Design Decisions

### D1. Parsing contract — assertions + VA anchors

`parse_assertions(text) -> list[dict]` scans every line for a bare `=` binding
(same rule as #49 `is_assignment_class`: `=` not preceded/followed by
`=`/`!`/`>`/`<`/`:`) and extracts `field=value`. A line may carry a VA anchor:
`0x<hex>: field=value` or `@0x<hex> field=value`. Result entry:
`{field, value, va: int|None, line_no}`. Also parsed from fenced code blocks
(```text/```asm) — the #49 reproduce convention emits `field=value` lines
inside a fenced block.

`_value_kind(value) -> ("hex"|"decimal"|"scaled"|"variable")`:
`0x…` prefix → hex; all digits → decimal; `X*K` (X non-numeric, K numeric) →
scaled; else variable. Values are normalized for compare (`0x1ffffffff` and
`8589934591` are the same integer).

### D2. VA → file offset (pefile sections)

`va_to_offset(pe, va, image_base) -> int | None`:
for each section, if `section.VirtualAddress <= rva < VirtualAddress +
VirtualSize` (rva = va − image_base), return `rva − section.VirtualAddress +
section.PointerToRawData`, provided the result is within
`PointerToRawData + SizeOfRawData` (else None = "mapped but not raw-resident").
No section match → None. `load_pe(binary_path)` wraps pefile with error
propagation as `PEError` (unparseable → caller reports error entry, no crash).

`disasm_at(binary_path, va, count=2) -> list[dict]`: capstone
`Cs(CS_ARCH_X86, CS_MODE_64|CS_MODE_32)` chosen from `pe.FILE_HEADER.Machine`
(0x8664 → 64, 0x14c → 32). Reads the raw bytes at the resolved offset,
disassembles up to `count` instructions, returns
`[{addr, mnemonic, op_str, imm: int|None}]` (`imm` = first immediate operand
value, None when the instruction has none).

### D3. Assertion rules (mechanical contract)

`check_assertion_disasm(assertion, insns) -> (ok, reason)`:

1. **numeric** (hex/decimal): pass iff some instruction in the window carries
   an immediate whose integer equals the claimed value byte-exact. Otherwise
   mismatch — including when the site disassembles to a register-source
   instruction (no immediate): "claim is constant but disasm has no immediate".
2. **scaled** `X*K`: pass iff some instruction mnemonic is in
   `(mul, imul)` and carries immediate K. Else mismatch
   ("claim scale K but disasm has no multiply with K").
3. **variable** (name): **SKIP** at the disasm level — without dataflow the
   register/variable identity is not mechanically decidable; recorded as a
   skipped check with the documented limitation (a2b5e25c's
   `frameRateNum=bitrate`-vs-`r13d` is caught by the cross-layer rule D4, not
   by disasm).

### D4. Cross-layer rule — report listing vs fact expected

`parse_expected_map(fact_text) -> dict[field, value]`:
the fact's `expected:` yaml field (#49) plus every `field=value` assertion
in its fenced code block (reproduce-emitted lines). Fields with `1`/`0`
values are kept (frameRateDen=1 must compare).

`check_report_listing(listing_text, fact_text, binary_path) -> dict` runs two
passes:

1. **cross-layer**: for each listing assertion, look up the field in the
   expected map. Present → compare by value kind:
   - numeric vs numeric → integer equality (byte-exact);
   - scaled vs same scaled string → pass; scaled vs anything else → mismatch;
   - variable vs variable → name equality; variable vs numeric (either
     direction) → mismatch ("claim says variable, fact says constant" — the
     a2b5e25c `gopLength=fps` vs `0xFFFFFFFF` shape).
   - field absent from expected map → SKIP (unverifiable cross-layer).
2. **disasm**: VA-anchored assertions run D3 against the binary. VA with no
   section match → error entry (RED3), not a crash.

Result: `{ok, mismatches: [{field, va, claim, expected|disasm, reason}],
checks: int, skipped: [field...]}`.

### D5. Fact-level gate — check_fact_disasm

`check_fact_disasm(fact_text, binary_path) -> dict`: runs D3 on the fact's own
VA-anchored assertions (numeric/scaled rules; variable → SKIP). This is the
fact-layer defense that would have caught F015 (`gopLength=0xFFFFFFFF` vs
disasm `0x1ffffffff` — byte-exact mismatch).

### D6. Integration

1. **`kunglao_verify.py::verify()`** — new keyword-only `binary_path: Path |
   None = None`. After the l2/overall computation and BEFORE writing the runs
   output: if binary_path is given, run `check_fact_disasm` on the fact text;
   on mismatch → `overall = "REJECTED"`, `out["disasm"] = result`. Fail-open:
   `ImportError` (capstone/pefile missing) or missing binary → result marked
   `{"ok": True, "skipped": reason}` and overall unchanged. Existing callers
   (no binary_path) are byte-for-byte unaffected.
2. **CLI** `tools/disasm_constant_check.py`:
   - `--report <listing.md> --reference <fact.md> --binary <pe>` → report
     mode (D4); `--fact <fact.md> --binary <pe>` → fact mode (D5);
   - `--json` output; exit 0 when ok, 1 when mismatches/errors.
   The report pipeline (hr-report handoff) invokes `--report` pre-handoff;
   the wiring lives in the analysis workspace, this repo ships the tool +
   entry point.

### D7. Synthetic PE fixture (tests)

Tests build a minimal PE64 by hand (DOS stub + PE header + one `.text`
section: FileAlignment 0x200, SectionAlignment 0x1000, image base
0x140000000) with crafted instructions at known RVAs (0x1010 offset from
section start):

| RVA | bytes | instruction | purpose |
|---|---|---|---|
| 0x1010 | `48 b8 ff ff ff ff 01 00 00 00` | `mov rax, 0x1ffffffff` | gopLength site |
| 0x101A | `b8 e8 03 00 00` | `mov eax, 0x3e8` | 1000 constant |
| 0x101F | `69 c0 e8 03 00 00` | `imul eax, eax, 0x3e8` | scaled-rule site |
| 0x1025 | `49 89 9c 24 34 11 00 00` | `mov [rsp+0x1134], r13d` | frameRateNum store |

pefile parses the crafted PE (fields consistent); capstone disassembles the
bytes. No external sample required.

## File layout

| File | Action | Purpose |
|---|---|---|
| `tools/disasm_constant_check.py` | CREATE | parser + pefile RVA→offset + capstone disasm + rules + CLI |
| `scripts/kunglao_verify.py` | UPDATE | `verify()` binary_path post-gate (fail-open) |
| `tests/test_disasm_constant_check.py` | CREATE | RED1-RED4 + a2b5e25c backtest + PE fixture builder |
| `references/schema.md` | UPDATE | VA-anchor + listing-check entry lines |

## Out of scope

- Dataflow/register tracing (variable claims stay SKIP at disasm level; the
  cross-layer rule covers the incident shape).
- PE imports/relocations/overlay — the checker only needs sections + .text
  bytes.
- Wiring the report pipeline's handoff-check.py (analysis-workspace side;
  this repo ships the CLI it calls).
