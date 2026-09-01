
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
  supersedes: [C-001]             # #879 lineage (optional): claims this one replaces
  superseded_by: C-002            # #879 lineage (optional): the replacing claim
  derived_from: []                # #879 lineage (optional): derivation (non-replacement) edges
```

**Lineage (#879)**: supersedes / superseded_by / derived_from are additive
optional fields; every target must be an existing claim id, self-reference
and supersedes/superseded_by cycles are violations — enforced as
carrier_consistency violation class `(g)`. The mechanical writer for the
replacement edge is `retract_claim.py --reason superseded --superseded-by
C-NN` (writes BOTH sides); a SUPERSEDED-status claim without an edge is
the "谁替代谁" gap #879 closes.

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

**INFERENCE-SCOPE convention (#48)**: `verifier_sign_off` MAY carry an
optional `evidence_path:` field (verifier's own evidence artifact; not
required, backward compatible). For **inferential** claims (statement or
fact text matches routing/causal patterns: `routing` / `route` /
`not on .* path` / `correction` / `corrects F<NN>` / `gate` /
`0 hits`/`0 occurrences` used as path evidence), the sign-off MUST cover the
inference itself: its evidence (`evidence_path` / `refute_attempt` /
`finding`) MUST contain an independent static-evidence marker (`xref`,
`disasm`, `decompile`, `capstone`, `ghidra`, `ida`, `call graph`,
`callsite`) and MUST NOT rely on `orchestrator-captured` evidence. A
byte-anchor-only sign-off (string counts, byte hashes) is insufficient for
routing/inference conclusions; violation downgrades PROVEN to STAMP
(`scripts/blind_gate.py::check_inference_blind_scope`). Additionally, when
the fact reports a negative hit (`0 hits` / `0 occurrences`) AND its
provenance self-reports an environmental fault (`stalled` /
`never reconnected` / `未触发` / `timeout`), independent static xref is
mandatory — the dynamic miss cannot establish a routing conclusion.

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

### VA-anchored assertions + disasm byte-exact check (#50)
Assignment-class assertions MAY carry a line VA anchor — `0x<hex>: field=value`
or `@0x<hex> field=value` — naming the instruction address that establishes the
value. `tools/static/disasm_constant_check.py` resolves VA → file offset via pefile
sections, disassembles the site with capstone, and compares byte-exact: numeric
claims (hex/decimal) against the instruction immediate; scaled claims (`X*K`)
require a `mul`/`imul` with immediate K at the site; variable-name claims SKIP
(not mechanically decidable without dataflow). `kunglao_verify.verify(...,
binary_path=pe)` runs this as a post-gate (mismatch → `overall = REJECTED`,
fail-open on missing binary/capstone/pefile); the report pipeline invokes
`disasm_constant_check.py --report <listing> --reference <fact> --binary <pe>`
pre-handoff to cross-check the listing against the fact's expected map AND the
disassembly (the a2b5e25c problem-1 cross-layer defense).

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

## machine_check oracle contract (#332, verifier records)

Every verifier verification record (kunglao-redteam output) must terminate in a
machine check: at least one `machine_check: {command, expected, actual, passed}`
with `passed: true`, byte/execution-level command. A record missing
`machine_check` or carrying `passed=false` fails schema validation — the fact
stays STAMP and must not promote to PROVEN. Exception path: `machine_check: none`
+ `reason` + `claim_kind`, accepted only when the kind is in the exception-allowed
list of `references/machine_check_map.yaml` AND matches the fact's `boundary_type`
(pure-CTI-class claims). Contract doc: `references/machine-check-contract.md`;
enforcement: `kunglao_verify.check_machine_check_contract` /
`machine_check_gate` / `verify()` L2-CONFIRMED gate (failure → overall=PARTIAL +
warning `MACHINE_CHECK_FAILED`).

recall_useful: pending
