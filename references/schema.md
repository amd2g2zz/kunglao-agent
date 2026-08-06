
**Heuristic**: are you reading or writing a schema? Read = this file. Write = use the matching template in templates/.
# Schema (DESIGN Appendix A — full, aligned with malware-veri-notes lint-notes.py)

## boundary_type (9 types)
`confirmed` | `capability_not_executed` | `link_not_closed` | `source_derived` | `numeric` | `observation` | `coordinate` | `pure_negative` | `contradiction`

- **open set** (require non-empty `promotion_gate`): `{capability_not_executed, link_not_closed, observation, source_derived, numeric}`
- aligns with lint `OPEN_BOUNDARY_TYPES`

## fact.status (lint `VALID_STATUS`)
`PROVEN` | `INFERRED` | `NEGATIVE` | `REFUTED` | `OPEN` | `DEFERRED` | `VERIFIED`

- **terminal**: `{PROVEN, VERIFIED, NEGATIVE, REFUTED, DEFERRED}`
- fact does NOT use `verify_status` (that's a note field)
- aligns with lint `LEGAL_COMBOS`: NEGATIVE pairs with pure_negative; REFUTED is high-confidence

## note.type (lint accepts)
`note` | `refutation` | `negative` | `deferred` | `caveat` | `supersede-update` | `open-question`

- **NOT** `finding` (lint L169 rejects it)
- **composite note**: `type ∈ {note, supersede-update, refutation}` AND `facts_used` length ≥ 2

## note.verify_status
`pending` | `passes` | `partial` | `fails` | `stale`

## claim-register entry
```yaml
- id: C-NNN
  statement: "<falsifiable claim>"
  answers_question: <q_id> | null
  boundary_type: <one of 9>
  promotion_gate: "<concrete evidence that would promote>"  # required if open
  promotion_attempts: 0           # int, §11 hook rejects dispatch when ≥3
  evidence_tier_attempted: 0      # int 0-3, §8.5 tier gate
  status: OPEN                    # one of VALID_STATUS
  source: cti                     # cti | static_re | dynamic_re | user_feedback | synthesis
  competitor_group: null          # q_id for model_selection (v1.7), else null
```

## claim_deps.yaml
```yaml
depends_on: {C-002: [C-001]}              # C-002 only true if C-001 is
competitor_groups: {q3: [C-005a, C-005b]}  # v1.7 mutually-exclusive K claims
```

## facts/_INDEX.md
`F<id> | <status> | <claim_id> | <one-line conclusion>` — one row per fact. Maintained by `scripts/update_index.py`.
