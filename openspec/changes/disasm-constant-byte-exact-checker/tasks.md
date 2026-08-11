## 1. Setup

- [ ] 1.1 Create branch `disasm-constant-check` off `dev` (one issue one PR one branch one worktree)
- [ ] 1.2 Confirm baseline test counts before changes (scripts/ 144 passed; tests/ 6 pre-existing failures recorded)

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 proposal.md (why: a2b5e25c problem 1, F015 byte-exact 空转, no cross-layer mechanical check)
- [x] 2.2 spec.md (REQ: fact→disasm byte-exact; report→fact cross-layer; verify() post-gate; CLI)
- [x] 2.3 design.md (D1-D7: parsing contract, VA→offset, rules, cross-layer, integration, PE fixture)
- [x] 2.4 tasks.md
- [x] 2.5 `openspec validate disasm-constant-byte-exact-checker` PASS

## 3. RED tests (write first, must fail)

- [x] 3.1 RED1: report listing `frameRateNum=bitrate` + reference fact expected `fps` → check_report_listing blocked
- [x] 3.2 RED2: listing matches disasm (`gopLength=0x1ffffffff` @0x140001010; `averageBitRate=bitrate*1000` @imul site) → passes; fact mode gopLength=0xFFFFFFFF @site → mismatch (F015 shape)
- [x] 3.3 RED3: VA outside all sections → error entry, no crash
- [x] 3.4 RED4: empty listing / no VA anchors → ok, zero checks
- [x] 3.5 a2b5e25c backtest: 10-assignment report listing (frameRateNum=bitrate / averageBitRate=bitrate*1000 / gopLength=fps) → blocked
- [x] 3.6 integration: verify(binary_path=pe) mismatch → overall REJECTED; without binary_path → unchanged

## 4. tools/disasm_constant_check.py implementation

- [x] 4.1 parse_assertions (bare-= + VA anchors) / _value_kind
- [x] 4.2 load_pe + va_to_offset (section RVA→raw) + disasm_at (capstone, arch from Machine)
- [x] 4.3 check_assertion_disasm (numeric byte-exact / scaled mul-imul / variable SKIP)
- [x] 4.4 parse_expected_map (expected: field + fenced field=value lines)
- [x] 4.5 check_fact_disasm + check_report_listing (cross-layer + disasm passes)
- [x] 4.6 main CLI (--report/--fact/--reference/--binary/--json; exit 0/1)

## 5. Wire into verify() (kunglao_verify.py)

- [x] 5.1 `verify()` binary_path keyword-only param + disasm post-gate (fail-open; mismatch → overall REJECTED, out["disasm"])
- [x] 5.2 Integration test GREEN (binary_path mismatch → REJECTED; absent → unchanged)

## 6. Docs + validation

- [x] 6.1 `references/schema.md`: VA-anchor convention + listing-check entry
- [x] 6.2 `python -m pytest scripts/` full pass (no new failures)
- [x] 6.3 `python -m pytest tests/` — new tests GREEN, 6 pre-existing failures unchanged
- [x] 6.4 `openspec validate disasm-constant-byte-exact-checker` PASS

## 7. PR + merge + cleanup

- [ ] 7.1 Commit (SDD first, then impl+tests), push branch, open PR to `dev` (body: Closes #50)
- [ ] 7.2 Squash-merge to dev, close issue #50
- [ ] 7.3 Remove worktree + delete branch; update master-plan.md delta
