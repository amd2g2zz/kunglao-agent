# issue-255-event-schema — tasks

## 1. RED tests

- [x] Tick axis: raw snapshot-row count accessor (absent ledger = real
      cold-start tick 0; unreadable = honest None), name pinned to the
      writer's constant (`tests/test_event_schema_255.py`)
- [x] Epoch stamps the tick by construction; explicit kwarg wins; axis
      advances monotonically; unreadable ledger = documented null
      (`tick_ledger_unreadable`)
- [x] Shrink: epoch out of AUTO_NULL_FIELDS (exact-tuple pin)
- [x] Timing wrapper: `timed()` measures a block (raising block included)
      and `monotonic_ms()` is a monotone integer clock
- [x] Emit-site population: rank_feeds carries the selected arm (empty
      action list keeps the honest null); verify carries measured
      duration_ms; claim_settled carries the settlement's hypothesis ref
      (no store = honest null)
- [x] Adversarial honesty: a plain emit never fabricates unknown fields;
      static single-axis audit forbids a second epoch counter outside the
      schema face + ledger passthrough

## 2. GREEN

- [x] `scripts/kunglao_log.py` — CONV_LEDGER_NAME / current_tick /
      monotonic_ms / timed; epoch inheritance at emit;
      AUTO_NULL_FIELDS = (duration_ms, arm, hypothesis_ref, matched_rule)
- [x] `scripts/priority_ratio.py` — rank_feeds arm (one-line, minimal
      merge surface for the in-flight round-seed lane)
- [x] `scripts/kunglao_verify.py` — measured duration_ms at the verify face
- [x] `scripts/register_proven_gate.py` — claim_settled hypothesis_ref
      (fail-open store read)
- [x] Rot-encoding tests updated: epoch faces in
      tests/test_observability_58.py and tests/test_logging_schema_818.py
- [x] tests/_tiers.py — new module in the fast registry

## 3. Validation

- [x] Targeted kunglao_log + emit-site families green
- [x] Full fast tier green (xdist -n 8)
- [x] comment-hygiene lint clean (ratchet: no new debt; kunglao_log.py
      baseline tightened for the rewritten rot comment)
- [x] ruff clean on touched files
- [x] deploy manifest untouched — verified unregistered (no write needed)
- [x] openspec validate clean

## 4. Review round 1 (four MEDIUMs, one pass)

- [x] emit docstring: document the deliberate no-explicit-null epoch face
      (explicit None == omitted; the axis is always stamped)
- [x] hypothesis_ref latest-selection is NUMERIC (parse the H-NNN suffix;
      a string max would return H-999 over H-1000) — boundary test pinned
- [x] honesty faces split: no_hypothesis (benign-empty) vs
      hypothesis_store_unreadable (broken store), threaded via the
      caller's null_reasons kwarg
- [x] governance pin: single-axis audit now walks scripts/+hooks/
      recursively and the exemption is pinned to its passthrough SHAPE;
      epoch-column contract added to the spec delta; passthrough
      governance comment at the mission_ledger surface; selected-arm
      ordering note at the rank_feeds call site
