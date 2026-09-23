# Distillation pipeline (5 stages) — issue #358

> Single reference for future external-knowledge distillation waves. Born from
> the #358 wave (2026-09-23). Owner directive: honest abandonment beats
> padding. Desensitized by construction: stages reference S-ids and licenses
> only; the URL→S-id ledger stays private (untracked scratch).

## Quality bar (standing)

Distillates must have **generality and heuristic value** — decision trees,
planning structures, approach-selection rules, environment-modeling patterns,
failure-mode taxonomies; knowledge that transfers across cases and sparks new
approaches. Case-specific insight does not survive stripping its names, and
insight that only re-solves the source's own case fails the bar. Applied
per-cluster (Stage 3); three-valued verdict: **distill / overlap / abandon**.
Sources landing zero cards are a normal outcome.

## Stage 1 — cleaning

Normalize raw extraction notes to house vocabulary (e.g. 补环境 → environment
stubbing; 纯算 → pure-algorithm recovery). Strip source-specific cruft (site
names, vendor constants, tool-build-specific numbers). Drop within-batch
duplicates (the same lesson surfacing in multiple sources is recorded once,
with member sources listed).

## Stage 2 — clustering

Group cleaned items ACROSS sources by methodology theme (e.g. env-stub
generation, peel ordering, planning chains, observation discipline, delivery
gates, failure ladders, contract formality). Clusters are the unit of
distillation. Singletons get explicit scrutiny: new theme or noise?

## Stage 3 — quality assessment

Per-cluster verdict against the standing bar, with recorded rationale:
- **distill** — general + heuristic + methodology-shaped.
- **overlap** — already covered by our cards (cite the card in the verdict).
- **abandon** — case-specific or out-of-lane; one desensitized line per
  abandoned item. Never generalize a case write-up into fake methodology by
  stripping names — if the insight does not survive stripping, it was not
  general.

**Methodology focus, three layers in priority order (owner ruling,
2026-09-23, binding on every card):**

1. **怎么规划** — why the path was ordered this way (what made each step the
   right next step given what was known at that point).
2. **遇到情况下一步怎么做** — decision rules as branch tables: situation →
   next action. The situation-action pair is the payload.
3. **隐含思路** — the mental model / invariant behind choices (e.g.
   "execution-form must be unwrapped before structural passes" is a boundary
   prior, not a step). Mine these from how the sources SEQUENCE their work,
   not only from what they state.

Facts/parameters/results are secondary payload — they enter a card only in
service of a decision rule. **The bar**: strip all concrete values from a
card; if no decision rules remain, it is reference material, not methodology
— it has not passed. Structurally: every card's soul-sections are the branch
table (situation → action) and the why-this-design reasoning.

**Clustering is algorithmic (owner ruling, 2026-09-23):** cluster assignment
comes from an actual algorithm over normalized items (e.g. TF-IDF +
k-means-class with k selected by silhouette), never from hand-waved themes.
Weak separation is an honest, reportable outcome; when structure is soft,
consolidation into cards happens at assessment stage with per-card cluster
provenance recorded.

## Stage 4 — conflict + duplicate vs existing references

- Overlap rows cite OUR card; external-derived content never silently
  overrides verified internal knowledge.
- **CONFLICT rows are explicit**: an external source contradicting our cards
  is reported as a conflict row (in the wave's gap report + private pipeline
  log); resolution requires new evidence, not provenance. Our doctrine stands
  until then; the conflict may be MENTIONED inside a card as a flagged
  alternative, never as a default.
- Duplicate rows fold into their first occurrence.

## Stage 5 — standardize then store

House card format; frontmatter carries: `source_id` (cluster member list),
`source_license` (matching order), `retrieved` (date), `epistemic:
external-derived` (never directly PROVEN — same class as WebSearch results),
`distill_bar: general+heuristic`, `dedup: new | overlap(<our-card>)`.
Generalized paraphrase; no third-party code; no verbatim copying beyond short
attributed conceptual excerpts where the license permits. Index registration
(re-library cards via the mapping; contracts via the top-level hand region)
+ re-pin + recall hits for domain keywords (tests). A card skips the library
until it passes standardization.

Internal-campaign waves (case-distilled lane): `source_id` = campaign id
(D-ids), `source_license: internal`, `epistemic: evidence-derived`;
community-source content from the campaign's own strategy material stays a
separate epistemic class and is marked `[community-claim]` inline — the three
classes evidence-derived ≠ community-claim ≠ external-derived never merge
in-card. Lane directory: `<domain>/case-distilled/` for internal campaigns,
`<domain>/external-distilled/` for external sources (provenance decides the
lane name).

### Card format contract (owner addendum, 2026-09-23)

The exemplars ARE the contract: a distillate card matches the style of

- `references/re-library/web/labs/web-re-quickref.md`
- `references/re-library/web/vm/jsvmp-triage.md`

(read both in full before drafting). That means: scenario-anchored commented
pseudocode groups (the comment carries the rule); tables for enumerable
rules; decision semantics as one-line verdict algebra followed by the
"why this design" paragraph where a choice is non-obvious; numbered step
protocols with tool names inline; a tool-face line when a tool exists or is
proposed; mermaid only for a genuinely load-bearing branching ladder (>3
levels). TL;DR-first holds WITHIN the card (progressive disclosure): the
opening purpose line + verdict algebra / step list are the TL;DR — not a
separate bolted-on block; detail sections below are self-titled. The blocks
are the distiller's own synthesis (same desensitization rules apply), never
copied source snippets.

Owner addendum (2026-09-23, structural): every card's soul-sections are the
branch table (situation → action) and the why-this-design reasoning. Chain
skeletons and reference tables serve these — reframe their emphasis
accordingly. The strip test decides admission: remove every concrete value;
whatever decision rules survive is the card.

## Wave artifacts

Per wave: private scratch ledger (S-id ↔ source, HEAD, license, retrieval
date) + private PIPELINE.md (cleaning log, cluster table with the algorithmic
assignment record, verdicts+rationale, conflict rows) + committed desensitized
gap report (`references/re-library/web/external-distilled/_GAP-REPORT.md` for
web-lane external waves; `<domain>/case-distilled/_GAP-REPORT-<campaign-id>.md` for internal
campaign waves) + PR-body summary. Scratch never commits; source material is
deleted from the worktree after merge.
