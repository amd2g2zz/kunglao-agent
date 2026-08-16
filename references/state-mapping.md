# State Mapping — kunglao claim workflow ↔ note schema two-layer mapping (#336)

kunglao tracks claims in `claim-register.yaml` with workflow states; facts carry
the malware-veri-notes schema (`status` = claim strength, `verify_status` =
verifier gate). Before #336 these vocabularies collided (facts used
`PARTIALLY-VERIFIED` as a schema status). This document is the explicit mapping
both consumers must implement.

## 1. Two-layer mapping table

| claim-register workflow state | fact `status` (claim strength) | `verify_status` (verifier gate) | `confidence` | `confidence_zh` |
|---|---|---|---|---|
| OPEN | OPEN | pending | (omit) | (omit) |
| STAMP (claimed, unverified) | INFERRED | pending | medium | 倾向于 |
| INFERRED (maker produced, no L1 yet) | INFERRED | pending | medium | 倾向于 |
| PARTIALLY-VERIFIED (L1 passed, L2 pending) | INFERRED | partial | medium | 倾向于 |
| PARTIALLY-VERIFIED + `boundary_type: pure_negative` | NEGATIVE | partial | high | 不支持 |
| PROVEN (maker + independent checker passed) | PROVEN | passes | high | 可确认 |
| DEFERRED | DEFERRED | pending | (omit) | (omit) |
| REFUTED | REFUTED | passes | high | 可确认 |

Notes:
- `PARTIALLY-VERIFIED` and `STAMP` are workflow states and MUST NOT appear in
  fact frontmatter (`lint_facts.py` errors with `BAD_STATUS`).
- `status` ≠ verification. `verify_status: passes` on an `INFERRED` fact means
  the applied gate passed but promotion is incomplete — that is what
  `partial` encodes; the register stays authoritative.
- Migration policy (migrate_facts.py): fact-file truth wins over `_INDEX.md`
  claims; claim strength is preserved (`PROVEN` stays `PROVEN`,
  `PARTIALLY-VERIFIED` → `INFERRED/partial`). Re-verification is never done by
  the migration.

## 2. Which layer each consumer reads

| Consumer | Layer | Reads |
|---|---|---|
| `scripts/convergence_check.py` (#331) | workflow | `claim-register.yaml` statuses + `facts/_INDEX.md` status column (`PARTIAL_STATUSES` subset matching) |
| `scripts/fact_contradiction_gate.py` | workflow | `facts/_INDEX.md` rows with status `PROVEN` |
| `scripts/kunglao_verify.py` (#332) | schema + extension | `claim_id`/`reproduce`/`expected`/provenance `recompute_script` |
| `scripts/lint_facts.py` (this change) | schema | all 12 mandatory + extension presence |
| malware-veri-notes `lint-notes.py` | schema + extension | fact fields incl. kunglao extension keys |
| malware-veri-notes `handoff-check.py` | schema | `verify_status` on cited notes |

`facts/_INDEX.md` status column is the WORKFLOW layer (kept as
`PROVEN`/`PARTIALLY-VERIFIED`/`NEGATIVE`/`DEFERRED` so convergence partial
counting and the contradiction gate keep working); the frontmatter carries the
schema layer. `migrate_facts.py` regenerates `_INDEX.md` from the migrated
frontmatter via `_workflow_status()`.

## 3. kunglao extension layer

`claim`, `reproduce`, `expected`, `verified` are kunglao extensions declared
ABOVE the schema (the schema's 12 mandatory fields are the contract; these four
are the kunglao L1-mechanical-verification contract, owned by #332). They are
required on every kunglao fact, validated for key presence by
`lint_facts.py`/`lint-notes.py`, and their value semantics belong to
`kunglao_verify.py`. `reproduce`/`expected` never double as `promotion_gate`.

## 4. ICD-203 nine rules → landing fields

| # | ICD-203 rule | Landing fields |
|---|---|---|
| 1 | Source quality & credibility | `provenance[].credibility` (Admiralty A1-F6) + `evidence/_index.json` `source_reliability` (icd203-source-reliability) |
| 2 | Uncertainty expression | `confidence` (high/medium/low, mandatory) + `confidence_zh` 5-verb mapping |
| 3 | Information vs judgment separation | `type: fact` vs note types; `source: analyst-judgment` singled out; `inference` excluded from PROVEN |
| 4 | Alternative hypothesis analysis | `alternatives: [{hypothesis, rejected_because}]` (ACH trace on major judgments) |
| 5 | Customer relevance | `claim_id` ↔ `claim-register.yaml` `answers_question` ↔ `task_spec.yaml` primary questions |
| 6 | Logical argumentation | body convention claim/evidence/warrant + `depends_on` edges + `## Code excerpt` |
| 7 | Judgment consistency / change | `supersedes` / `superseded_by` / `amends` (two-way, lint-checked) + #331 retraction chain |
| 8 | Accuracy | verification chain: `verify_status` + `verified` + `reproduce`/`expected` L1 oracle (#332) |
| 9 | Visual evidence | `provenance` `role: screenshot` entries |

## 5. Follow-up hooks (not part of this change)

- `agents/kunglao-worker.md` (#310 domain): point the fact-writing section at
  `templates/fact-frontmatter.md` and the slugged id convention.
- `scripts/convergence_check.py` / `scripts/priority.py` (#331 domain): consume
  this mapping when reconciling register statuses with fact statuses.
- `handoff-check.py` (malware-veri-notes, live dir): integration hook is a
  one-liner — run `lint_facts.py <workspace>` before the notes gate; lint
  failure = non-conforming (wrapper is independent until then).
- Fact FILE renaming to `F<NNN>-<slug>.md` (the canonical layout per
  convergence_check v1.9.8 note) needs coordinated register/worker/prompt
  updates; #336 slugs the frontmatter `id` only. New facts should use the
  slugged filename from the start.
- `claim-register.yaml` `fact:` fields keep the old ids for now (kunglao_verify
  resolves `facts/<id>.md`); update together with the file rename.
