# tasks — issue-799-seal-learning-channel

## 1. The RED contract
- [ ] tests/test_seal_799.py: pins for the five acceptance faces
      (forged stash edit, worker PROVEN cap, unsealed row refusal +
      byte-unchanged posteriors, oracle-status L7, propensity receipt
      L8, + unarmed legacy control, tamper refusal, additive-seal shape)
- [ ] confirmed RED before implementing

## 2. The faces
- [ ] `rlvr/learning_seal.py` — #736 construction, key path, armed(),
      row_sha, sign_row, verify_row, trusted_rows
- [ ] `incremental_reward`: stash + row sealing, settle wall,
      read-face filter, oracle-status wall, propensity cross-check
- [ ] `q_cells`: row sealing, fold/matchers/totals filters, step cap
- [ ] `strategy_store`: append sealing, load_rows filter,
      PosteriorStrategyStore verified reads

## 3. Gates
- [ ] pins green; liveness no-degrade; quality_gates --quick ALL-PASS;
      `pytest -m "fast and not docs"` belt; ruff clean
- [ ] detect_changes scope check; review-gate mint; CI green
