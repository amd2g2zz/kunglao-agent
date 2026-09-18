# fix-248-reproduction-oracle — tasks (post2 slim scope)

## 1. RED tests

- [x] generation-language goal pins `reproduction`; weak selection
      refused (`tests/test_reproduction_oracle_248.py`; declarative
      passives must NOT classify — post2 review LOW note, tightened)
- [x] intake pre-write contract refuses to LAND the weak selection for a
      generation-language goal (`validate_values` wiring)
- [x] replay observation does not settle an algorithm-class claim —
      re-routed to input-contract, claim stays open
      (`tests/test_settle_by_need.py`)
- [x] unknown evidence class / untyped need fail closed
      (`tests/test_settle_by_need.py`)

## 2. GREEN

- [x] Piece 1 — intake pinning + separate admission
      (`scripts/oracle_anchors.py`: `is_generation_language`,
      `derive_verification_method`, `intake_method_gate`,
      `validate_values` tightening)
- [x] Piece 3 — settle by need (`scripts/settle_by_need.py`)

## 3. Validation

- [x] Targeted: `tests/test_oracle_anchors.py tests/test_settle_by_need.py
      tests/test_reproduction_oracle_248.py tests/test_replay_equivalence_172.py`
      green
- [x] Full fast tier (`-m "fast and not docs"`), ruff clean on touched files
- [x] `openspec validate fix-248-reproduction-oracle` exit 0

## Moved to #259 (v0.1.6) — cut from post2 by the slim ruling

- [ ] Closed-book admission/verdict machinery
      (`scripts/replay_equivalence.py`: `reproduction_client` execution,
      `admission_errors`/`load_ws_client`, verifier-sampled novel inputs
      `sample_novel_input`/`novel_input_pair`, recorded novel-input floor
      + schema-lint face, source-derived reference adapter). Salvage from
      WIP commit `6c0b410` of `fix/248-reproduction-oracle` (code, tests,
      mock-signer experiment notes in `REVIEW-NOTES-248.md`).
