# tasks — issue-715-source-reliability

## 1. The learned source-reliability Beta (source-reliability-715)

- [ ] `scripts/rlvr/source_reliability.py`: evidence labels
      (`evidence_labels`, `source_class_of`), the closed
      `raw > derived > inferred` vocabulary
- [ ] `record_refutation` / `record_confirmation` / `record_outcome` —
      append-only `source-reliability.jsonl` rows via the shared append
      primitive; invalid labels refused loud, never raised
- [ ] `fold()` -> `ReliabilityView` with per-(source_class,
      context_class) cells + per-source_class marginals
- [ ] `posterior()` backoff (cell -> marginal -> prior) and `theta()`
      (stdlib betavariate, anchor-deterministic default)
- [ ] store shared via `strategy_store.store_root()` (env override),
      fail-open reads, loud-result writes
- [ ] RED: refuted -> beta++; confirmed -> alpha++; generalization to a
      new context; no-rule uniform prior; invalid label refusal

## 2. Credit weighting (source-credit-weighting-715)

- [ ] `reliability_weight(evidence)` — theta draw when labeled, 1.0 when
      not ("if available")
- [ ] `apply_source_reliability(step_credit, theta)` — the
      `step_credit *= source_reliability_theta` composition, clamped
- [ ] RED: low-reliability source credit discounted against a confirmed
      one; unlabeled evidence neutral; exploration answer comes from the
      posterior width (settled-bad effectively never retried)

## 3. Verification

- [ ] two spec deltas registered; `npx openspec validate
      issue-715-source-reliability` exit 0
- [ ] `tests/test_source_reliability_715.py` green with `-n 2`
- [ ] registration surfaces: `scripts/README.md` catalog rows,
      fast-tier registration, deploy manifest re-write, baseline
      re-emits
- [ ] comment/formal-code lints clean; deploy manifest re-emitted
