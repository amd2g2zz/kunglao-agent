
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

**CONFLICT convention (#47)**: two PROVEN facts are same-topic when their
topic-key sets intersect (same `claim_id`, or overlapping `sample_refs`, or
overlapping `cites`). If their conclusions differ (whitespace-normalized) and
neither declares `supersedes:`/`superseded_by:` naming the other, the pair is
a CONFLICT (needs-resolution): `fact_contradiction_gate.py` blocks claim
promotion to PROVEN (downgrade to STAMP) until a link is added. Same
conclusion on the same topic = converged, not conflicting.

## fact.expected (assignment-class value-assertion convention, #49)

`expected:` is verified byte-exact by `kunglao_verify.py::l1_mechanical`. Two shapes:

- **Non-assignment-class** (no bare `=`): verified by whole-blob sha256. Use for
  hex/sha literals (`0x5a4d`, a 64-hex sha256) and pure API call sequences
  (`calls Foo(a, b)`).
- **Assignment-class** (contains a bare `=` that is not `==`/`!=`/`>=`/`<=`/`:=`):
  MUST list concrete value assertions — each binding a field to a value with its
  offset/register/immediate source — so `l1_mechanical` has per-field byte-exact
  targets. Example:
  `frameRateNum=fps; frameRateDen=1; averageBitRate=bitrate; maxBitRate=bitrate; gopLength=0xFFFFFFFF`.
  The reproduce command MUST emit each assertion as a `field=value` (or
  `field: value`) line; `l1_mechanical` compares field by field and reports the
  mismatched field name on failure (it does NOT reduce the blob to one sha256).

### lint gate (D1/D3)
Assignment-class `expected` lacking concrete value assertions (e.g. only
`field=??` placeholders) is **rejected** by `check_assignment_expected` and MUST
NOT promote to PROVEN/VERIFIED — there are no byte-exact targets. The lint runs
before L1 inside `verify()`; rejection forces `overall = REJECTED`.

### migration (`--grace` / `--grace-scan`)
Existing PROVEN facts whose `expected` is assignment-class-but-no-assertions need
backfilling. Run `kunglao-verify.py <ws> --grace-scan` to enumerate them, then
either backfill value assertions or run a single verify pass with `--grace`
(warn-only, non-blocking) for one migration cycle.

### BREAKING (a2b5e25c)
This is a breaking change for any existing assignment-class fact whose `expected`
carried only an API sequence or placeholders — it is now rejected until backfilled
with concrete value assertions. Drive: the a2b5e25c incident where F015 (NVENC
init) passed L1 with an API-sequence-only `expected` while the field assignments
were all-reversed; the old whole-blob sha256 hid the per-field mismatch.
