# tasks — issue-740-progress-coupling

## 1. The RED contract
- [x] tests/test_progress_coupling_740.py: 7 pins (unchanged-skip,
      no-accumulate, register/status change rebuild, stall crossing,
      drain semantics preserved, first build persists + emits)
- [x] confirmed RED (4 failed) before implementing

## 2. The gate
- [x] scripts/verification_ladder.py: round_close computes the input
      signature (shape minus time projections), skips persist+emit on
      equality, persists the signature with the doc otherwise

## 3. Gates
- [x] 7/7 green; ladder neighbors 229 green; ruff clean; formal-code 0;
      comment-hygiene clean; manifest --verify 573 OK
- [ ] review-gate mint; CI green

## Named follow-ups (same issue)
- [ ] Face 2 act-or-suppress (stale/drift faces); Face 3 park; Face 4
      dispatch exit/duration telemetry
