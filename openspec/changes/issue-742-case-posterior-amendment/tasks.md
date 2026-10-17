# tasks — issue-742-case-posterior-amendment

## 1. The RED contract
- [x] tests/test_case_amendment_742.py: 10 pins (flip-once + idempotence,
      within-class no-op, the four honest gaps, append-only wall,
      runner-mass composition, refusal surfacing, pass wiring)
- [x] confirmed RED (10 failed) before implementing

## 2. The faces
- [x] `case-amendment/1` registered in NATIVE_SCHEMAS
- [x] `_effective_pair_outcomes` (both stamps, last-amendment-wins)
- [x] `reconcile_case_settlements` (trigger arithmetic, belief-first
      ±1 with the Beta(1,1) floor + WARN, audit row, telemetry)
- [x] `run()` wires the leg; result reports `case_amendments`

## 3. Gates
- [ ] 10/10 green; neighbors (730/678/634/733/731/430) green; ruff;
      formal-code 0; comment-hygiene clean; manifest --verify
- [ ] review-gate mint; CI green
