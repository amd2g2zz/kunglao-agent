# fix-248-reproduction-oracle — tasks

## 1. Experiment (done first, mandatory)

- [x] Build mock web-signer fixture + proposed machinery; demonstrate
      (a) replay-only cannot pass a novel-input pair, (b) closed-book client does.
      Result: PASS (seed 248); near-miss md5 client also caught.

## 2. RED tests (`tests/test_reproduction_oracle_248.py`)

- [x] generation-language goal pins `reproduction`; weak selection refused
- [x] artifact without runnable client refused at admission
- [x] recomputed != recorded refused with fabrication reason
- [x] novel-input pair: closed-book matches source-derived reference; replay-only cannot
- [x] replay observation does not settle an algorithm-class claim (re-routed to input-contract)

## 3. GREEN

- [x] Piece 1 — intake pinning (`oracle_anchors.py`)
- [x] Piece 2 — admission closed-book (`replay_equivalence.py`)
- [x] Piece 3 — settle by need (`settle_by_need.py`)

## 4. Validation

- [x] `uv run python -m pytest -q` full suite — no NEW failures beyond the
      pre-existing environment set (see REVIEW-NOTES-248.md for the
      failure-by-failure disposition; registration gates all green after
      manifest/catalog/hygiene refresh)
- [x] `openspec validate fix-248-reproduction-oracle` exit 0
