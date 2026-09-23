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

## Wave artifacts

Per wave: private scratch ledger (S-id ↔ source, HEAD, license, retrieval
date) + private PIPELINE.md (cleaning log, cluster table, verdicts+rationale,
conflict rows) + committed desensitized gap report
(`references/re-library/web/external-distilled/_GAP-REPORT.md` for web-lane
waves) + PR-body summary. Scratch never commits; source material is deleted
from the worktree after merge.
