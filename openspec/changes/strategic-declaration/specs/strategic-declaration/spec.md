# Spec Delta

## Purpose

Defines the dispatch-time strategic route declaration: every dispatch
records its strategic action — or the explicit absence of one — as an
appended `strategic-action/1` row in the unified experience ledger,
the absence maps toward SURRENDER per the disposition algebra at
settle time, and the sampler reconciliation reads the row as the
preferred declared face. A silent `default / declared:false` norm is
replaced by an attributable declaration or an attributable gap.

## ADDED Requirements

### Requirement: Every dispatch records its strategic route or the explicit gap

Each dispatch that passes the gate's ALLOW tail MUST append exactly one
`strategic-action/1` declaration row to the unified experience ledger
carrying `claim`, `route`, `propensity`, `declared`, `trace_id`, and
`ts`. A dispatch declaring a route in the closed set (`FIGHT`,
`BYPASS`, `INVEST` — the action_space STRATEGIC vocabulary) MUST set
`declared: true` with the route; a dispatch declaring nothing (no
marker, or a marker naming a strategy id that is not a route word)
MUST set `declared: false` with `route: null` and `propensity: null`.
Silence and placeholder route words are both forbidden.

#### Scenario: Declared route

- **WHEN** a dispatch prompt carries `[strategy FIGHT]`
- **THEN** exactly one row with `declared: true`, `route: "FIGHT"`, a
  finite `propensity` in [0, 1], and the dispatch's `trace_id` lands in
  the ledger

#### Scenario: Undeclared dispatch

- **WHEN** a dispatch prompt carries no route declaration
- **THEN** exactly one row with `declared: false`, `route: null`, and
  `propensity: null` lands in the ledger

#### Scenario: A strategy id is not a route

- **WHEN** a dispatch prompt carries `[strategy first-pass]` (not a
  closed-set word)
- **THEN** the row records the gap (`declared: false`,
  `route: null`), never a fabricated route

### Requirement: Declaration rows append with last-row-wins semantics

Repeated dispatches for the same claim MUST append (history preserved,
no dedupe, no idempotence on this face); the LAST row is the live face
for every consumer, claim-scoped where the consumer knows the claim.
This mirrors the strategy-log reader's semantics and is distinct from
the episode face's immutable-one-row-per-episode contract.

#### Scenario: Repeated dispatch

- **WHEN** a claim is dispatched twice, first BYPASS then FIGHT
- **THEN** two rows exist in order and the last-row reader resolves
  the FIGHT row as the live face

### Requirement: The declared propensity is the smoothed prior share

A declared row's `propensity` MUST be the route's Laplace-smoothed share
of the workspace's PRIOR declared dispatch rows over the recent
declaration window (named module constants; a route with no prior
declarations under any history keeps a strictly positive propensity —
a probability-0 draw for a taken action is invalid for IPS), computed
BEFORE the dispatch's own row appends — a choice never raises its own
propensity. The uniform prior over the closed set falls out on a cold
workspace. A gap row carries no propensity.

#### Scenario: Cold workspace draws the uniform prior

- **WHEN** the first declared dispatch on a workspace declares FIGHT
- **THEN** its propensity is the uniform prior over the closed set

#### Scenario: The prior precedes the choice

- **WHEN** a second dispatch declares the same route
- **THEN** its propensity reflects only the prior window's smoothed
  share, never the choice itself

#### Scenario: A never-declared route stays positive

- **WHEN** a dispatch declares a route with zero prior declarations
  under an existing history
- **THEN** its propensity is strictly inside (0, 1) (the smoothing
  floor), never 0.0

### Requirement: Absence classifies toward SURRENDER per the disposition algebra

At settle time a pure mapping MUST send a `declared: false` row — and
a missing row — toward the disposition algebra's residual word
(SURRENDER, the unfinished gate's disposition), using the existing
seven-word vocabulary. The vocabulary MUST NOT be extended, and the
episode classifier keeps its precedence (an oracle pass outranks the
residual). The mapping helper is the ONE derivation site: the
disposition record's join face (`disposition_fields`) consults it for
the gap face, and the derivation of the word itself degrades to a
documented sentinel (never an import-time crash) if the algebra ever
drops the unfinished gate.

#### Scenario: The gap row maps toward the residual word

- **WHEN** the settle side reads a `declared: false` declaration row
  (or no row at all)
- **THEN** the mapping yields SURRENDER, a member of the unextended
  seven-word disposition vocabulary

#### Scenario: A declared row maps nothing

- **WHEN** the settle side reads a declared route row
- **THEN** the absence mapping yields no disposition word (the route
  flows into the episode record's strategic action instead)

#### Scenario: A vocabulary refactor cannot crash the import

- **WHEN** the disposition algebra's gate table no longer carries the
  unfinished gate
- **THEN** the residual word degrades to the documented sentinel with
  one warn instead of raising at import

### Requirement: The sampler reconciliation prefers the declaration row

The dispatch-gate reconciliation view MUST read the live declaration
row as the PREFERRED declared face for the strategic route (additive
`declared_route` / `declared_propensity` / `declared_source` on the
view). With no row present — or on any reader outage — the view MUST
stay byte-identical to its pre-change shape: the envelope method-family
face remains the fallback, the existing `reconcile_declaration` path
is unchanged, and the route token never enters the method-family
enforcement faces.

#### Scenario: The row is surfaced

- **WHEN** the workspace holds a declared-route row and the gate
  reconciles a dispatch
- **THEN** the view carries the row's route, propensity, and source
  beside the unchanged method-family reconciliation

#### Scenario: The fallback holds

- **WHEN** no declaration row exists (or the reader fails)
- **THEN** the view keeps exactly its pre-change keys, and the
  method-family path stays green
