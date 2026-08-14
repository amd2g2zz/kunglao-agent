# Tasks — fixture condensed-excerpt conversion ban (#58)

## 1. Setup

- [x] 1.1 Worktree wt58 on branch `fixture-excerpt-lint` at dev baseline `fd53d93` (one issue / one PR / one branch / one worktree)
- [x] 1.2 Baseline measured: scripts/ 226 passed; tests/ 350 passed + 1 skipped + 6 pre-existing failures (test_acceptance, test_skill_lte_500_lines, 4x test_convergence_completeness)

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 `openspec new change fixture-excerpt-lint` scaffolded (README + .openspec.yaml)
- [x] 2.2 proposal.md (why: a2b5e25c *1000; layering vs #50/#49; 3 rules)
- [x] 2.3 design.md (D1-D6 + R1-R3; D1 = layering table; D2 = conversion heuristic; D4 = sVar discriminator; D5 = recall/precision stance)
- [x] 2.4 spec.md (REQ: lint() R1 conversion + R3 speculation / unit: + resolved: exemptions / clean→0 / CLI exit 0/1/2 / cross-ref #50+#49)
- [x] 2.5 tasks.md
- [x] 2.6 `openspec validate fixture-excerpt-lint` PASS

## 3. RED tests (write first, must fail)

- [x] 3.1 `test_regression_nvenc_asterisk1000_flagged`: issue #58 excerpt verbatim → the two `*1000` statements flagged (R1, severity=high); other statements on the lines not flagged
- [x] 3.2 `test_regression_unit_annotation_exempts`: same excerpt + `// unit: bps (kbps*1000)` on the *1000 line → 0 violations
- [x] 3.3 `test_sVar_speculation_flagged`: `sVar1 = bitrate;` → R3 violation
- [x] 3.4 `test_sVar_resolved_annotation_exempts`: `sVar1 = bitrate; // resolved: ...` → 0
- [x] 3.5 `test_sVar_faithful_copy_and_cast_not_flagged`: `sVar1 = sVar2;` and `sVar1 = (long)sVar2;` → 0
- [x] 3.6 `test_clean_faithful_excerpt_zero`: a clean excerpt (raw assignments, no scaling, no speculated sVar) → 0 violations (precision guard)
- [x] 3.7 `test_variable_multiply_not_flagged`: `x = a * b;` → 0 (no numeric operand)
- [x] 3.8 `test_module_docstring_cross_references_50_49`: module docstring names #50 and #49 (non-duplicate)
- [x] 3.9 `test_cli_exit_codes_and_json`: CLI exit 0 on clean / 1 on violations / 2 on missing file; JSON well-formed
- [x] 3.10 Confirm RED: `python -m pytest tests/test_fixture_excerpt_lint.py -q` → ModuleNotFoundError (confirmed: `No module named 'fixture_excerpt_lint'`)

## 4. GREEN — scripts/fixture_excerpt_lint.py

- [x] 4.1 `lint(excerpt_text) -> dict`: R1 conversion detector (numeric-literal scaling; KNOWN_UNIT_SCALES→high), R3 speculation detector (identifier discriminator + TYPE_KEYWORDS), `unit:` / `resolved:` exemptions
- [x] 4.2 `main()` CLI: argparse `<excerpt.c>`, JSON report, exit 0/1/2
- [x] 4.3 module docstring cross-references #50 and #49 as complementary, non-duplicate
- [x] 4.4 Confirm GREEN: `python -m pytest tests/test_fixture_excerpt_lint.py -q` → 19 passed

## 5. Reference doc

- [x] 5.1 `references/excerpt-lint.md`: the 3 rules + `unit:`/`resolved:` contracts + layering vs #50/#49 (NEW file; no failure-modes-* edits)

## 6. Validation

- [x] 6.1 `python -m pytest tests/test_fixture_excerpt_lint.py -q` → 19 passed
- [x] 6.2 `python -m pytest scripts/ -q` → 226 passed, 0 failures
- [x] 6.3 `python -m pytest tests/ -q` → 369 passed + 1 skipped + the SAME 6 pre-existing failures (350 baseline + 19 new)
- [x] 6.4 `openspec validate fixture-excerpt-lint` PASS (final)

## 7. Commit + PR

- [x] 7.1 Commit SDD artifacts (`844165f`)
- [x] 7.2 Commit RED tests (`bbf51f0`)
- [x] 7.3 Commit GREEN impl + reference doc (this commit)
- [ ] 7.4 Push branch, `gh pr create --base dev --head fixture-excerpt-lint`
- [ ] 7.5 Do NOT merge; orchestrator verifies first
