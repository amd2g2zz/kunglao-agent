# tasks — issue-667-step-experience-ledger

## 1. The step ledger (step-record/1)

- [x] `scripts/rlvr/step_ledger.py`: `sha_of`, `record_step` (hash-only whitelist builder, append, fail-open)
- [x] `hooks/step_record_capture.py`: PostToolUse shadow capture (ws resolve, row build, exit 0 always)
- [x] wiring: hook_activation deploy table + deploy-manifest re-emit
- [x] RED: hash-only pin, fail-open pin, hook payload pin

## 2. The evidence-credit ledger (evidence-item/1 + credit-amendment/1)

- [x] `record_evidence` (step_ref + certified verdict + artifact sha)
- [x] `amend` lifecycle: escrow → confirm|revoke|expire; CONFIRM requires certified; revoke targets the producing step's evidence
- [x] `expire_pending` (TTL) + `replay_credit_ledger` byte-identity
- [x] RED: lifecycle fixtures (confirm/refute/expiry), farming-nets-zero, replay byte-identity, determinism

## 3. The intervention log (intervention/1)

- [x] `record_intervention` (shadow-only, hash-only)
- [x] RED: row shape + fail-open

## 4. Verification

- [x] three spec deltas registered; `openspec validate issue-667-step-experience-ledger` exit 0
- [x] focused suites green; full fast suite green (golden zero-change pin)
- [x] ruff clean; comment/invocation/formal-code lints clean
- [x] deploy manifest re-emitted + verify; `release_receipt.py --check` rc 0
