# issue-487-query-formulation — spec delta: query-formulation

## ADDED Requirements

### Requirement: problem-representation-before-retrieval

The distillation act SHALL begin with a mechanical problem-enumeration
step (`formulate_problem`) that reads ONLY structured workspace state —
`evidence/die.json` and `evidence/apkid.json` (the environment snapshot),
the obstacle registry `runs/obstacles/` (through the `rlvr.obstacles`
reader), and the trigger itself — and emits a `query-formulation/1`
document: 3 to 5 facets of closed kind (`format_family`, `technique`,
`tool`, `error_signature`), each facet carrying 1–6 normalized terms and
per-term provenance (source file + field + raw value). No term without
provenance; no LLM, no network, no budget debit; a facet count below 3 is
legal only via the evidence-bounded rule (floor reached by the three
standing facets: format_family, technique, tool — with the one honest
degradation that a degenerate sub-3-character trigger token with no
evidence yields two standing facets, since the technique fallback
tokenizes at 3+ characters).

#### Scenario: rich environment yields provenance-carrying facets

- **WHEN** the workspace holds apkid evidence with `summary.packer =
  ["aplib"]`, `summary.anti_analysis = ["anti_debug"]`, one obstacle row
  `{kind: encryption_layer, cause: "...", method_family: ...}`, and a
  `shelf-miss: android:sign-recovery sample=bins/libsign.so` marker
- **THEN** `formulate_problem` returns 4–5 facets, every term carrying a
  provenance entry whose `source` names the file (and field) it came from

#### Scenario: thin environment still formulates three standing facets

- **WHEN** the workspace holds only the shelf-miss marker (no probe
  evidence, no obstacles)
- **THEN** the formulation still carries the three standing facets
  (format_family falls back to the sample suffix map or `binary`;
  technique falls back to the token components; tool carries the token),
  and no facet term lacks provenance

#### Scenario: formulation failure never blocks the act

- **WHEN** the formulation module raises or is absent (partial deploy)
- **THEN** the distill act proceeds unformulated with one rate-limited
  warn (fail-open rider) and the pre-#487 prompt shape

### Requirement: per-facet-retrieval-coverage-matrix

Each facet SHALL be retrieved independently over the local re-library
(default `references/re-library/`, resolved relative to the module's
install parent; explicit corpus override for fixtures), producing a
`distill-coverage/1` matrix: per facet, the hit cards (corpus-relative
paths + matched terms + score), a verdict, and a summary block. A card
covers a facet when at least ceil(n/2) of its n distinct terms match on
word boundaries in the identically-normalized card text (the
half-ceiling rule, minimum 1 — a single-term facet asks for its one
term, a two-term facet for one, a five-term facet for three); hits are
ranked (score desc, path asc) and capped at 5. The
coverage matrix SHALL be recorded per distill act in the
`distill_result` audit row's detail.

#### Scenario: facet independence

- **WHEN** two facets would return overlapping cards
- **THEN** each facet's row is computed and recorded independently (no
  cross-facet merging; coverage is measured per facet)

#### Scenario: the audit row carries the matrix

- **WHEN** a distill act completes through the e2e tick step
- **THEN** the act's `distill_result` row detail carries the coverage
  summary (facets / hits / reformulated_hits / corpus_lack)

### Requirement: empty-facet-disambiguation

An empty facet SHALL be disambiguated with EXACTLY ONE reformulation: the
facet re-worded from its provenance terms (raw provenance values
tokenized, deduped against the original terms, capped 6) and re-retrieved.
A hit on the retry is verdict `reformulated-hit`; still empty — or no
rewordable material — is verdict `corpus-lack`, the real shelf-miss: the
distill act proceeds exactly as today (the corpus-lack facet becomes a
web-face priority in the dispatch prompt; nothing is blocked and no
budget is debited by disambiguation itself).

#### Scenario: bad query recovers via one reformulation

- **WHEN** a facet's curated terms miss the corpus but its provenance
  terms match a card
- **THEN** the facet verdict is `reformulated-hit` with the
  reformulated query recorded, and the card is recorded as its hit

#### Scenario: genuine corpus-lack

- **WHEN** a facet's terms and its reformulation both match nothing
- **THEN** the facet verdict is `corpus-lack` and the distill act
  proceeds (never blocked, never re-reformulated a second time)

### Requirement: formulation-beats-fragments-fixture

The repository SHALL carry a fixture corpus + staged workspace
(`tests/fixtures/query-formulation-487/`) and a pinned test proving good
formulation beats fragment queries: the formulated facets' per-facet
hit-rate on the fixture corpus strictly exceeds the raw trigger-token
fragment baseline's, with exact counts pinned (regression pin, not a
threshold smoke).

#### Scenario: the pinned comparison holds

- **WHEN** the fixture test formulates over the staged workspace and
  retrieves per facet, then retrieves with the fragment baseline terms
- **THEN** formulated hit-facet count > fragment hit-facet count with
  both counts exactly pinned in the assertion

### Requirement: production-stamp-carries-formulation

The production closure SHALL stamp the formulation + coverage into
`runs/distill-trigger.json` (via `online_distill.stamp_trigger(...,
formulation=...)` after `formulate_for_trigger`), and the orchestrator's
shelf-miss dispatch protocol (SKILL.md) SHALL direct the dispatch prompt
to carry the stamped facets + coverage (hit cards as starting points,
corpus-lack facets as web-face priorities).

#### Scenario: the closure stamp carries the matrix

- **WHEN** the SubagentStop closure scans a workspace with a fresh
  shelf-miss marker
- **THEN** `runs/distill-trigger.json` carries the formulation (facets
  with provenance) and the coverage matrix beside the trigger rows
