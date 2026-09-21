# eval-v1 changelog

## eval-v1 (#299 smoke tier — initial)

- Corpus layout created: `eval/v1/tasks/smoke/` with three constructed
  targets (ground truth by construction, seeded variants of known
  mechanism families):
  - `go-arx-v1` — SHA-1-family KDF, mutated K0/golden/rot-base constants;
    constant-hit (static) + pair-match (reproduction, >= 12 of 16) oracles.
  - `js-sign-v1` — obfuscated-style signer bundle, two load-bearing
    constants + two decoys; constant-hit + replay-roundtrip over published
    and checker-minted probes.
  - `py-derive-v1` — 64-bit pure-algo derivation; replay-roundtrip over
    published and checker-minted probes (anti-digest-table).
- Task-unit schema: `schemas/eval-task-v1.json` (+ validator in
  `scripts/eval_dataset.py`).
- Mechanical checker: `scripts/eval_checker.py` (METRIC emission,
  arithmetic verdict, evidence archive, structured failure signals,
  toolchain-skip contract).
- Smoke-tier runner: `scripts/eval_smoke_runner.py` (#295-shaped results
  rows; `--candidate-for` = the #236 control-arm execution surface;
  `--baselines` = 1/k guessing floor).
- Held-out path contract: `EVAL_CORPUS_PREFIXES` +
  `filter_distiller_sources` — eval tasks never enter the #298
  distillation corpus.

## Rules for future versions

- A version used for a capability claim is never mutated in place: churn
  mints `eval-v2/` + a new changelog section (seeds may be re-drawn;
  variants must stay divergent).
- Every task keeps its `seed` so any unit can be re-minted
  byte-identically.
