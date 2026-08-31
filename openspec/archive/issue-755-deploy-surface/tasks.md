# Tasks: issue-755 (+ issue-758 G2/G3 tail — absorbed into this change)

Per task one commit; TDD RED before each implementation.

- [X] T0 openspec skeleton (proposal/design/tasks; G2/G3 absorption noted)
- [X] T1 = A2 `_item_agents_refresh` + tests
- [X] T2 = G2 frame markers in init render + golden regen + G3 merge module
      (`scripts/claudemd_frame.py`, `_item_claudemd_merge`) + tests
      (tests/test_claudemd_g2g3_758.py)
- [X] T3 = A4/A5/A6 config trio items + tests
- [X] T4 = A7 `_item_uv_sync` + tests
- [X] T5 = A1 staleness detection + SKILL.md doc + test
- [X] T6 = registry entry `migrate_to_0_1_4` integration + guard scans
- [ ] quality gates (in flight): targeted suites → sanitized-PATH full run → receipt →
      quality_gates → ruff → evidence+mint → PR `fix(#755,#758): …`
      with `Closes #755` + `Closes #758`
