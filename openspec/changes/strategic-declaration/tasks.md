# Tasks

## 1. RED — the declaration contract

- [x] 1.1 Write `tests/test_strategic_declaration_1005.py` RED: a
  declared-route dispatch writes EXACTLY ONE `strategic-action/1` row
  into `runs/experience.jsonl` carrying `{claim, route, propensity,
  declared: true, trace_id, ts}`; run it, watch it fail
- [x] 1.2 RED: an undeclared dispatch writes the explicit gap row
  (`declared: false`, `route: null`, `propensity: null`); a
  `[strategy <id>]` marker naming a non-route id is NOT a route
  declaration
- [x] 1.3 RED: repeated dispatch for the same claim APPENDS (history
  preserved, no dedupe); the LAST row is the live face
- [x] 1.4 RED: the builder's validation matrix (route in the closed
  set or null; propensity finite in [0, 1]; declared:true requires
  route + propensity; declared:false requires the null face; ts
  calendar-validated; claim required; trace_id optional)

## 2. The pure builder + readers + mapping

- [x] 2.1 Add `build_declaration_row` (pure) to
  `scripts/rlvr/strategic_action.py` with the full validation matrix
- [x] 2.2 Add `append_declaration` (append-only, revalidated through
  the builder, no dedupe, no event) and `declaration_rows` /
  `latest_declaration` (last-row-wins, claim-scoped)
- [x] 2.3 Add `route_propensity` (prior share over declared rows,
  uniform cold start, None for the gap) and pin the
  compute-before-append property from the gate side
- [x] 2.4 Add `absence_disposition` (None and gap rows map toward
  SURRENDER; declared rows map nothing) with the word DERIVED from
  `rlvr.disposition`'s vocabulary + gate table; pin the seven-word set
  unextended and the residual gate
- [x] 2.5 Extend `disposition_fields` to speak the declaration shape
  (declared route onward, gap to the None face) and verify the
  episode-face tests stay byte-green

## 3. The dispatch seam

- [x] 3.1 Add `_log_strategic_declaration` to `hooks/dispatch_gate.py`
  (same `[strategy <id>]` parse face, closed-set route check,
  fail-open print-on-error) and call it at the ALLOW tail beside the
  strategy-log writer
- [x] 3.2 Verify the gate-driven tests: exactly one row per dispatch,
  gap rows on markerless and non-route dispatches, append history,
  prior-share propensity across two dispatches

## 4. The sampler reconciliation face

- [x] 4.1 Add `_strategic_declared_face` to
  `hooks/worker_budget_sinks.py` (fail-open, last-row reader) and
  layer the preferred declared face into `_sample_reconciliation`
  (additive keys `declared_route` / `declared_propensity` /
  `declared_source`)
- [x] 4.2 Verify: no row keeps the view byte-identical (the envelope
  family face stays the fallback); the existing `reconcile_declaration`
  path and the sampled-binds suites stay green; a reader outage
  degrades to the fallback with one warn

## 5. Documentation + gates

- [x] 5.1 Open the openspec change `strategic-declaration`
  (proposal / design / tasks + the capability spec delta) and pass
  `openspec validate`
- [x] 5.2 Update the rlvr README's strategic-action section for the
  declaration face (module contract text only)
- [x] 5.3 Run the affected suites in ONE invocation (sampled-binds,
  decompat, strategic-stopping, decision teeth, disposition family)
  plus `scripts/local_gate.py --skip-pytest` expecting ALL GREEN
