# tasks — issue-430-govern-sweep

## 1. The RED contract
- [x] tests/test_sample_govern_430.py: 10 pins across the families
      (named sites, guard faces, the cold-start split, the inner
      counter, the shared activation face); confirmed RED (9 failed)

## 2. The warns
- [x] 16 sites + the two cold-start splits, zero return-value changes

## 3. Gates
- [ ] 10/10 green; ruff; manifest; formal-code + comment-hygiene clean
- [ ] review-gate mint; CI green
