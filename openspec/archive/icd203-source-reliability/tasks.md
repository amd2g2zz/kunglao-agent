# Tasks: icd203-source-reliability

- [ ] 1. RED: test source_reliability field exists in every index entry
- [ ] 2. RED: test mechanical defaults by type (capture→A1, CTI→C5, json→B3, sandbox→D3, yara→B2, decompile→A2)
- [ ] 3. RED: test --rel custom map overrides defaults
- [ ] 4. GREEN: implement `_default_reliability` + `_apply_reliability` in build_evidence_index.py
- [ ] 5. GREEN: add `--rel` CLI option
- [ ] 6. GREEN: extend measure_blind_coverage.py with `--reliability` mode
- [ ] 7. GREEN: update _render_md to include source_reliability column
- [ ] 8. pytest全绿 + validate
