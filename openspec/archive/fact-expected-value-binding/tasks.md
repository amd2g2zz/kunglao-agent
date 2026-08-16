## 1. Setup

- [x] 1.1 Create branch `fact-expected-value-binding` off `dev` (one issue one PR one branch)
- [x] 1.2 Confirm `uv sync` + `pytest` baseline green before changes (record the count)

## 2. RED tests (write first, must fail)

- [x] 2.1 RED1: test that an assignment-class `expected` (contains `=`, field names, immediates) WITHOUT value assertions is rejected by `check_assignment_expected`
- [x] 2.2 RED2: test that an `expected` listing concrete value assertions (field=value + source) passes the lint and is compared byte-exact per assertion
- [x] 2.3 RED3: test that a pure API-sequence `expected` (no assignment indicators) is NOT flagged assignment-class and passes existing rules unchanged
- [x] 2.4 a2b5e25c regression: test that F015 (nvenc_create_d3d11_encoder, API-sequence-only expected) is REJECTED; after backfilling value assertions, PASSES byte-exact

## 3. Assignment-class classifier (design D4)

- [x] 3.1 Implement `is_assignment_class(expected_text)` keyword heuristic: `=` (not `==`), field-name patterns, hex immediates (`0x...`), register refs, offset refs
- [x] 3.2 Unit-test classifier boundary on F015 + 2-3 sibling facts + pure-sequence fixtures

## 4. Value-assertion parser

- [x] 4.1 Implement `parse_value_assertions(expected_text)` extracting field=value + offset/register/immediate bindings
- [x] 4.2 Unit-test parser on NVENC-style expected (frameRateNum=fps; ...; gopLength=0xFFFFFFFF) + edge cases

## 5. lint-reject gate (design D1, D3 - inside kunglao_verify.py)

- [x] 5.1 Implement `check_assignment_expected(fact)` in `kunglao_verify.py`: assignment-class + no value assertions -> reject with reason listing detected tokens
- [x] 5.2 Wire `check_assignment_expected` into the promotion path (before `l1_mechanical`); rejection blocks PROVEN/VERIFIED promotion
- [x] 5.3 RED1 + RED2 + RED3 tests now pass (GREEN)

## 6. Targeted byte-exact compare (design D2)

- [x] 6.1 Extend `l1_mechanical` (or add `compare_value_assertions`): when value assertions present, compare each against reproduce output / fixture per-field; do NOT reduce whole `expected` to one sha256
- [x] 6.2 Report mismatched fields by name (not just PASS/FAIL)
- [x] 6.3 a2b5e25c "one wrong assignment among several" scenario test passes

## 7. --grace migration flag

- [x] 7.1 Add `--grace` flag: warn-only mode (logs affected facts without rejecting) for one-cycle migration
- [x] 7.2 Enumerate affected existing PROVEN facts (F015 + siblings) in `--grace` output

## 8. Docs / schema convention

- [x] 8.1 Update `references/schema.md` (or equivalent) with the assignment-class `expected` value-assertion convention (field=value + offset/register/immediate source)
- [x] 8.2 Note the BREAKING change for existing facts (must backfill)

## 9. a2b5e25c regression + backfill

- [x] 9.1 Backfill F015 `expected` with correct value assertions (frameRateNum=fps; frameRateDen=1; averageBitRate=bitrate; maxBitRate=bitrate; gopLength=0xFFFFFFFF)
- [x] 9.2 Verify F015 now passes byte-exact; pre-backfill version rejected (regression test green)
- [x] 9.3 Run `--grace` over the full fact base to identify any other assignment-class facts needing backfill

## 10. Validation + PR

- [x] 10.1 Full `pytest` green (count >= baseline + new tests)
- [x] 10.2 `openspec validate fact-expected-value-binding` PASS
- [x] 10.3 PR to `dev` (one issue one PR), reference #49 + a2b5e25c
