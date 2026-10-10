# tasks — issue-653-verifier-anchor

## 1. The re-run receipt contract

- [x] extract `_verifier_dispatch_text(claim, stamp, timeout_s)` (pure builder)
- [x] prompt carries the receipt block shape + the recorded-output distrust rule
- [x] RED: prompt-builder tests (contract lines present; sibling-free claim pin)

## 2. The landing gate

- [x] `_verify_note_receipts(note, verdict)` — verified requires ≥1 well-formed receipt (integer rc, 64-hex out-sha); refuted exempt
- [x] wire into `_run_verifier_act`: refusal → ONE warn, verdict settles absent (0.0), prediction settlement skipped, promotion replaced by a recorded refusal
- [x] RED→GREEN: `tests/test_verify_receipts_653.py` (valid/malformed/absent/refuted + the gate wiring pins)

## 3. Verification

- [x] focused suites green (checkpoints-adjacent: terminal settlement, verifier wiring)
- [x] ruff clean; comment-hygiene / invocation-hygiene / formal-code clean
- [x] deploy manifest re-emitted (checkpoints.py sha row) + `--verify`
- [x] `openspec validate issue-653-verifier-anchor` exit 0; `release_receipt.py --check` rc 0
