## Tasks

- [x] T1: Reconnaissance — read cc.decide() L523-544, kd.decide() L115-147, decide-output.json; produce field comparison table
- [x] T2: RED test — `tests/test_decide_schema_routing.py`: 8 tests proving mismatch and validating both producers
- [x] T3: GREEN — `schemas/convergence-check-output.json`: new schema matching cc.decide() actual output
- [x] T4: Validate — full pytest suite: 494 passed, 2 pre-existing failures (unchanged), 1 skipped
