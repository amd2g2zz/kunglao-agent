# tasks — issue-740-face4-dispatch-telemetry

## 1. The RED contract
- [x] tests/test_dispatch_telemetry_740.py: 4 pins (the four fields on
      the completion row; the non-worker silence; the settle receipt's
      telemetry keys; the blocked exit)
- [x] confirmed RED (3 failed) before implementing

## 2. The enrichment
- [x] step_grain.settle_step additive telemetry keys
- [x] round_closure: _kernel_faces returns the receipt; the emit moves
      after the kernel faces and enriches; non-worker stops stay silent

## 3. Gates
- [x] 4/4 green; step-grain + event-stream neighbors green; ruff clean;
      formal-code 0; comment-hygiene clean; manifest --verify 573 OK
- [ ] review-gate mint; CI green
