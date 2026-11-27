# Design

## Context

`strategic-action/1` is already a native schema of the experience
family (`consolidated_ledger.NATIVE_SCHEMAS`), and the #985-#988 wave
shipped the EPISODE face: `rlvr.strategic_action.record()` writes one
immutable row per episode (refusing an absent action — absence is
expressed as no row) and the disposition producer joins the LAST row
per claim through `disposition_fields`. But no production writer fed
the face: the workspace audit found every recent strategy-log row
reading `strategy: "default", declared: false`, and zero
`strategic-action/1` rows in the wild. The dispatch seam is the one
point every real dispatch passes (the ALLOW tail of
`hooks/dispatch_gate.py`, where the strategy-log row is already
written), so it is the natural producer — but its contract differs
from the episode face by design: a dispatch that declares nothing must
still be RECORDED (the honest gap), and retries must preserve history.

## Goals / Non-Goals

Goals:
- One appended declaration row per dispatch on the ALLOW tail, with
  the brief's field set `{claim, route, propensity, declared,
  trace_id, ts}`.
- The honest gap: an undeclared dispatch writes `declared: false` /
  `route: null` / `propensity: null` — never silence, never a
  placeholder route word.
- Append history with last-row-wins semantics (the strategy-log
  reader's model), claim-scoped where a consumer knows the claim.
- A prior-share behavior propensity that never includes the current
  choice (no self-raising propensity).
- Settle-side absence mapping toward SURRENDER via the disposition
  algebra's own vocabulary, asserted by a pure function.
- Sampler reconciliation prefers the row as the declared face;
  fallback keeps the pre-change view byte-identical.

Non-Goals:
- No new gate decision, no REJECT path, no enforcement (the
  declaration is a record, not a constraint).
- No change to `runs/strategy-log.jsonl` IO (that rel belongs to the
  telemetry-family slice) — the declaration row is a NEW row type in
  `runs/experience.jsonl` beside the strategy-log row, not a
  replacement.
- No change to the episode face (`record()` stays idempotent-per-
  episode and refuses absent actions — different contract, different
  question).
- No extension of the seven-disposition vocabulary.
- No new telemetry event words (the dispatch tail is high-frequency;
  the unified-log dispatch row is its observability face).

## Decisions

### D1. One stamp, two faces, one discriminator

Both faces live under `strategic-action/1` in the same consolidated
experience file; the discriminator is structural: episode rows carry
`episode_id` + `action`, declaration rows carry `route` + `declared`
(+ `trace_id`). `disposition_fields` speaks both, so the disposition
producer's last-row-per-claim join keeps working unchanged — a
declared route becomes the record's strategic action, a gap row
becomes the None face whose classifier residual is SURRENDER.

### D2. The declaration rides the strategy-log marker face

The route face parses the SAME `[strategy <id>]` marker the
strategy-log writer parses, checked against the closed set (uppercased
token ∈ `STRATEGIC_ACTIONS`, derived from the action_space registry).
A marker naming a strategy id (the novelty face's use) is NOT a route
declaration — it lands the gap row. One parse face, two consumers, no
new prompt protocol.

### D3. APPEND history, last row is the live face

`append_declaration` never dedupes and never emits an event (the tail
is high-frequency; admission-ticket symmetry is kept by reporting the
failed append). `latest_declaration(ws, claim=None)` returns the last
row (within the recent window), claim-scoped when the consumer knows
the claim — the same reversed-join the disposition producer uses and
the strategy-log reader's semantics. The reader faces bound their
window (`DECLARATION_HISTORY_MAX`, the strategy-log writer's cap
pattern) because the consolidated experience file is append-only and
grows one row per dispatch; the settle-side full join keeps its own
`read()` face.

### D4. Propensity = smoothed prior share, computed before the append

`route_propensity(ws, route)` = the route's Laplace-smoothed share of
PRIOR declared rows over the recent window (`(hits + alpha) /
(total + alpha*K)`, named module constants): a route never declared
under an existing history stays strictly inside (0, 1) — a
probability-0 draw for a taken action is invalid for IPS (the
propensity-coherence family's pathology) — and the cold start falls
out as the exact uniform prior (the audit's own evidence says the cold
choice is prior-only). The gate computes it BEFORE appending the
dispatch's row, so the behavior policy that "chose" the route cannot
include the choice itself.

### D5. Absence maps toward SURRENDER through the algebra's vocabulary

`absence_disposition(row_or_None)` returns the residual word for
`None` and for gap rows, `None` for declared rows (the route is
evidence, not a disposition). The word is DERIVED from
`rlvr.disposition`'s `DISPOSITIONS` + `GATE_FOR_DISPOSITION` (the
unfinished gate's disposition) — imported, never restated; a test pins
the seven-word set unextended and the word's gate.

### D6. Reconciliation: preferred face, byte-identical fallback

`_sample_reconciliation` gains a fail-open reader of the live
declaration face; when a row exists the view gains additive keys
(`declared_route` / `declared_propensity` / `declared_source`), and
with no row — or on any reader outage — the view is exactly the
pre-change shape. The route token never enters the method-family
reconciliation or the sampled-binds check (different vocabularies; the
enforcement faces stay untouched).

### D7. Fail-open at the seam, always

The gate writer's posture mirrors the strategy-log write: one stderr
note on any failure, never a raise into the gate, never a changed
verdict. The reconciliation reader degrades to the fallback face with
one rate-limited warn.

## Risks / Trade-offs

- Two shapes under one stamp could confuse a naive consumer that
  assumes the episode shape. Mitigation: the discriminator is a single
  structural key (`declared` present), `disposition_fields` is the
  documented join face, and the module docstring names both faces.
- The prior-share propensity is a measured *declaration* prior, not a
  learned policy — honest for now (nothing else samples routes), and
  the derivation is documented on the row producer.
- Declaration rows grow the experience file (one row per dispatch).
  The family's consolidated append is cheap; a retention face belongs
  to the family owner, not this change. The READER faces are bounded
  (`DECLARATION_HISTORY_MAX` recent-window cap) so the per-dispatch
  cost does not grow with history; the settle-side full join stays the
  family's own `read()` face.

## Migration Plan

Additive only: the schema stamp is already registered (liveness
pre-seeds it at 0), the writer is a new fail-open call beside an
existing one, and every reader degrades to the pre-change view when no
rows exist. No migration, no backcompat shims, no config.

## Open Questions

- Whether the orchestrator skill should surface the declared route
  textually at dispatch time (a prompt-side affordance) — deferred;
  the marker face already exists and the skill text needs no change
  for the writer to record honestly.
