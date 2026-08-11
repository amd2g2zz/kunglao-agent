## ADDED Requirements

### Requirement: VA-anchored fact value assertions SHALL be byte-exact checked against capstone disassembly

`tools/disasm_constant_check.py::check_fact_disasm(fact_text, binary_path)` SHALL parse the fact's `field=value` assignment assertions (the #49 convention, bare `=` not `==`/`!=`/`>=`/`<=`/`:=`) with their line VA anchors (`0x<hex>:` prefix), resolve VA → file offset via pefile sections (file offset = RVA − section delta), disassemble the site with capstone, and compare: numeric claims (hex/decimal) against the instruction immediate byte-exact; scaled claims (`X*K`) against a `mul`/`imul` at the site carrying immediate K. Variable-name claims SHALL be recorded as skipped (not mechanically decidable without dataflow). A claim whose VA is not mapped by any section SHALL produce an error entry, never a crash.

#### Scenario: fact claims gopLength=0xFFFFFFFF but disasm is mov rax, 0x1ffffffff
- **WHEN** a fact's VA-anchored assertion claims `gopLength=0xFFFFFFFF` at a site that disassembles to `mov rax, 0x1ffffffff`
- **THEN** the check reports a byte-exact mismatch (the a2b5e25c F015 shape) and `ok` is false

#### Scenario: scaled claim without a multiply at the site
- **WHEN** a claim says `averageBitRate=bitrate*1000` at a site whose disassembly contains no `mul`/`imul` with immediate 1000
- **THEN** the check reports a mismatch ("claim scale K but disasm has no multiply with K")

#### Scenario: VA outside all sections
- **WHEN** a claim's VA maps to no PE section
- **THEN** the check records an error entry for that claim and continues; no exception escapes

#### Scenario: empty listing / no VA anchors
- **WHEN** the input text has no assignment assertions or none carry a VA
- **THEN** the check returns an ok result with zero checks (no crash)

### Requirement: report code listings SHALL be cross-checked against fact expected values and disassembly

`check_report_listing(listing_text, fact_text, binary_path)` SHALL compare every report-listing assertion by field name against the reference fact's expected value map (`expected:` field + fenced `field=value` lines, #49): numeric vs numeric by integer equality; scaled vs identical scaled string; variable vs variable by name; numeric vs variable in either direction SHALL be a mismatch ("claim says variable, fact says constant"). VA-anchored listing assertions SHALL additionally run the disasm rules. Fields absent from the expected map SHALL be skipped.

#### Scenario: report claims frameRateNum=bitrate while fact expects fps
- **WHEN** the report listing asserts `frameRateNum=bitrate` and the reference fact's expected map binds `frameRateNum=fps`
- **THEN** the cross-layer check reports a mismatch and the report is blocked

#### Scenario: report claim matches fact expected and disasm
- **WHEN** a listing assertion's value equals the fact's expected value and (if VA-anchored) the disasm immediate
- **THEN** the check passes

### Requirement: verify() SHALL run the disasm gate as a post-step when a binary is provided

`scripts/kunglao_verify.py::verify()` SHALL accept a keyword-only `binary_path`; when provided, `check_fact_disasm` runs after the existing lint/L1/L2 computation and a mismatch downgrades `overall` to `REJECTED` with the disasm result recorded in the output. Fail-open: `ImportError` (capstone/pefile absent) or unreadable binary → gate skipped, overall unchanged. Callers that do not pass `binary_path` are unaffected.

#### Scenario: verify with a mismatching fact and binary
- **WHEN** `verify(ws, fact_id, binary_path=pe)` runs on a fact whose VA-anchored numeric assertion mismatches the binary disassembly
- **THEN** `overall` is `REJECTED` and the output carries the disasm mismatch detail

#### Scenario: verify without binary_path
- **WHEN** `verify(ws, fact_id)` runs without a binary
- **THEN** the disasm gate does not run and the output shape is unchanged

### Requirement: the checker SHALL expose a CLI for report-handoff pre-gate use

`tools/disasm_constant_check.py` SHALL run as a CLI: `--report <listing> --reference <fact> --binary <pe>` (report mode) and `--fact <fact> --binary <pe>` (fact mode), with `--json` output and exit 0 when ok / 1 when mismatches or errors. This is the entry point the report pipeline invokes before handoff.

#### Scenario: report handoff pre-gate CLI
- **WHEN** the report pipeline runs `disasm_constant_check.py --report listing.md --reference fact.md --binary sample.exe`
- **THEN** the CLI prints JSON verdict and exits 1 when the listing carries a cross-layer or disasm mismatch
