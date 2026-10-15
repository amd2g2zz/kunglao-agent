# tasks — issue-715-source-reliability

## 1. The learned source-reliability Beta (source-reliability-715)

- [x] `scripts/rlvr/source_reliability.py`: evidence labels
      (`evidence_labels`, `source_class_of`, `has_source_labels`), the
      closed `raw > derived > inferred` vocabulary
- [x] `record_refutation` / `record_confirmation` / `record_outcome` —
      append-only `source-reliability.jsonl` rows via the shared append
      primitive; invalid labels refused loud, never raised
- [x] `fold()` -> `ReliabilityView` with per-(source_class,
      context_class) cells + per-source_class marginals
- [x] `posterior()` backoff (cell -> marginal -> prior) and `theta()`
      (stdlib betavariate, anchor-deterministic default)
- [x] store shared via `strategy_store.store_root()` (env override),
      fail-open reads, loud-result writes
- [x] RED: refuted -> beta++; confirmed -> alpha++; generalization to a
      new context; no-rule uniform prior; invalid label refusal

## 2. Credit weighting (source-credit-weighting-715)

- [x] `weighted_step_credit(items)` on the step-credit module
      (`scripts/rlvr/step_credit.py`): per-item
      `item_credit(meta) × source_reliability_theta`; the module's
      `step_credit` entry routes through it
- [x] unlabeled evidence weights 1.0 — byte-identical pre-discount
      score; the store is read only when a labeled item is present
- [x] the learned face neither reads nor changes the module's own
      credibility modulation (interfaces recorded in design D5)
- [x] RED: low-reliability source credit discounted against a confirmed
      one; production `step_credit` carries the discount; unlabeled
      evidence neutral; exploration answer comes from the posterior
      width (settled-bad effectively never retried)

## 3. Verification

- [x] two spec deltas registered; `npx openspec validate
      issue-715-source-reliability` exit 0
- [x] `tests/test_source_reliability_715.py` +
      `tests/test_step_level_credit_712.py` green together with `-n 2`
      (the rebase onto the step-credit branch; this suite's pins run
      through the merged interface)
- [x] registration surfaces: `scripts/README.md` catalog rows,
      fast-tier registration, deploy manifest re-write, baseline
      re-emits
- [x] comment/formal-code lints clean; deploy manifest re-emitted
