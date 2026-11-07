# Proposal

## Why

The 2026-11-05 workspace audit (issue-1005) measured the learning loop
acting but never closing on the strategic face: recent `strategy-log`
dispatch rows all read `strategy: "default", declared: false` — no
FIGHT / BYPASS / INVEST route was ever recorded — and the
`strategic-action/1` schema (already registered as a native experience
schema) had no dispatch-time writer at all, so every disposition record
inherited the `None` action face and the classifier's SURRENDER
residual was fed by silence instead of by an explicit, attributable
declaration. A silent default is not a decision: the learning feed
cannot attribute a route the loop never admitted choosing (or not
choosing).

## What Changes

- **Dispatch-time declaration (the S5 face)**: the dispatch gate's
  ALLOW tail — the same seam that already writes the strategy-log row —
  appends one `strategic-action/1` declaration row into the unified
  experience ledger (`runs/experience.jsonl`, via the consolidated
  family append) carrying `{claim, route, propensity, declared,
  trace_id, ts}`.
- **The route face reuses the existing `[strategy <id>]` marker**: a
  marker naming one of the closed route words (`FIGHT`, `BYPASS`,
  `INVEST` — the action_space STRATEGIC vocabulary) declares the route;
  a markerless dispatch, or a marker naming a strategy id that is not a
  route word, lands the honest gap row (`declared: false`,
  `route: null`, `propensity: null`). Silence is never the norm, and no
  placeholder route word exists.
- **Append history**: repeated dispatches append (no dedupe, no
  idempotence on this face) — the LAST row is the live face, mirroring
  the strategy-log reader's semantics. The episode face of the stamp
  (one immutable row per episode) is unchanged.
- **Prior-share propensity**: the declared route's behavior propensity
  is its Laplace-smoothed share of the workspace's PRIOR declared
  dispatch rows over the recent declaration window (a route never
  declared under an existing history stays strictly inside (0, 1) —
  a probability-0 draw is invalid for IPS; the uniform prior over the
  closed set falls out on a cold workspace), computed BEFORE the
  dispatch's own append so a choice never raises its own propensity.
- **Absence classifies toward SURRENDER at settle**: a pure mapping
  (`absence_disposition`) sends a gap row — or no row at all — toward
  the disposition algebra's residual word (SURRENDER, the unfinished
  gate's disposition). The seven-word disposition vocabulary is
  consumed, never extended; the episode classifier still owns the
  final verdict; the join face consults the mapping as its one
  derivation site, and the word's own derivation degrades to a
  documented sentinel instead of crashing on a vocabulary refactor.
- **The disposition producer keeps joining the LAST row per claim**:
  `disposition_fields` now speaks both faces of the stamp (episode
  rows unchanged; declaration rows map the declared route onward and
  the gap to the None face), so the declared route flows into the
  disposition record with no producer change.
- **Sampler reconciliation consumes the row**: the dispatch-gate
  reconciliation view (`hooks/worker_budget_sinks._sample_reconciliation`)
  prefers the declaration row as the declared face for the strategic
  route (`declared_route` / `declared_propensity` / `declared_source`
  on the view); with no row the view stays byte-identical to the
  pre-change shape (the envelope method-family face remains the
  fallback, and the existing `reconcile_declaration` path is
  unchanged).

## Capabilities

### New Capabilities
- `strategic-declaration`: the dispatch-time strategic route
  declaration — one appended `strategic-action/1` row per dispatch
  (declared route with prior-share propensity, or the explicit gap),
  the append-history live-face semantics, the settle-side
  absence-toward-SURRENDER mapping, and the sampler reconciliation's
  preferred declared face.

### Modified Capabilities
- None (no pre-existing spec store; the episode-disposition behavior
  this change builds on is defined by the redteam-tdd change's
  `episode-disposition` spec, and its vocabulary and precedence are
  consumed here, never extended).

## Impact

- `scripts/rlvr/strategic_action.py` — the declaration face (builder,
  append, readers, prior-share propensity, absence mapping,
  declaration-aware `disposition_fields`); the episode face and the
  registered stamp are untouched.
- `hooks/dispatch_gate.py` — one new fail-open writer at the existing
  ALLOW tail (`_log_strategic_declaration`), called beside the
  strategy-log writer; no gate decision changes.
- `hooks/worker_budget_sinks.py` — `_sample_reconciliation` layers the
  preferred declared face; fail-open, additive keys only.
- Telemetry: none new (the declaration row rides the registered
  `strategic-action/1` stamp; no new event words — the unified-log
  dispatch row remains the observability face of the tail).
- Tests: `tests/test_strategic_declaration_1005.py` (new) plus the
  affected suites (sampled-binds, decompat, strategic-stopping,
  decision teeth, disposition family).
