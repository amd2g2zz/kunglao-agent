# REVIEW-NOTES-248

Implementer notes for issue #248 (algorithm claims settle on reproduction,
not endpoint observations). Completed across several resumptions after
transient backend failures; final mechanical refreshes (manifest/catalog/
comment-hygiene) done by the orchestrator.

## Repair round 2 (post re-review, reviewer t5-rev248-b)

Re-reviewer t5-rev248-b verified the round-1 B1/B2 fixes (probes at
/tmp/rev248b-probes) and found one NEW blocking defect.

### D1 (blocking) — the recorded-novel floor was forgeable

The floor was `any(row.get("novel_input"))` — a submitter-controlled
boolean with no verifier-side freshness check — and the schema membership
rule forced EVERY pair (including "novel" ones) inside `captured_inputs`,
so novelty outside the capture inventory was inexpressible. Probe
(ws-forge): echo-table client over 6 captured rows (full ts x nonce
coverage, zero computation) with one captured row relabeled
`novel_input: true` -> admission_errors=[], equivalence_verdict=True ->
PROVEN. Reproduced on the staged code before fixing.

Fix (`scripts/replay_equivalence.py`):
- `admission_errors` now enforces doc-local freshness on every recorded
  novel-input pair: its `input_id` must sit OUTSIDE `captured_inputs`
  ("pair 'cap-04' id inside captured_inputs — not fresh") and its core
  assignment (projection onto the declared variables) must differ from
  every captured row's core ("pair 'x' core duplicates captured row
  'cap-00' — not fresh"). The floor plus freshness runs on EVERY
  admission at both wired faces.
- `_pair_errors` (schema lint) matches: a `novel_input` pair is exempt
  from the captured-inventory membership rule (novelty is expressible)
  and a `novel_input` pair whose id is inside `captured_inputs` is
  refused by the lint with the same not-fresh reason, so the wired
  verdict face refuses the forgery at the schema face.
- Honest fixtures re-pinned to the corrected shape: novel rows carry ids
  OUTSIDE `captured_inputs` (tests/test_reproduction_oracle_248.py
  `_verdict_artifact` -> "novel-01", tests/test_replay_equivalence_172.py
  `_novel_pair` -> "novel-01", tests/test_oracle_anchors.py armed fixture
  -> "novel-06"). The reviewer's ws-ok/ws-b2 workspaces were forged in
  the round-1 shape (novel id inside the inventory — the shape D1
  exploits) and now refuse by design; the corrected honest shape is what
  the pinned tests encode.

Evidence (RED-first, all 5 failed on the staged code):
- `test_admission_refuses_relabelled_captured_row_as_novel` (probe
  replica, direct face — admitted before).
- `test_equivalence_verdict_refuses_relabelled_captured_row_as_novel`
  (probe replica, wired verdict face — verdict True before).
- `test_admission_refuses_novel_row_whose_core_duplicates_a_captured_row`
  (fresh id outside the inventory, core re-runs cap-00 — admitted
  before).
- `test_schema_lint_allows_novel_row_outside_captured_inputs` (lint
  refused the honest novel row before — novelty was inexpressible).
- `test_schema_lint_refuses_novel_row_inside_captured_inputs` (lint was
  silent on the relabeling before).
Post-fix: the ws-forge probe is refused at all four faces (schema lint,
admission, equivalence_verdict, unverified-PQ) with the named reason.

### Non-blocking (round 2)

- N2: doubled "vocabulary" in the `scripts/settle_by_need.py` module
  docstring fixed.
- N3: dead first artifact write removed from the
  `test_armed_verdict_passes_with_valid_artifact` fixture
  (tests/test_oracle_anchors.py) — the artifact is written once, after
  the client is stamped.

### Repair-round-2 evidence

- Targeted suites green (see round-1 list); openspec validate exit 0
  with the freshness contract added to the admission requirement (two
  new scenarios); manifest `--write` refreshed; comment-hygiene clean.

## Repair round 1 (post review-FAIL)

An independent reviewer FAILED the staged diff with two reproduced
blocking defects; both are fixed RED-first, plus the two named
non-blocking fixes.

### B1 (blocking) — novel-input bit never enforced at a production face

The wired admission faces (`kunglao_record.check_claim_admission`,
`convergence_check._reproduction_face`) reach `admission_errors` with
`reference_source=None`; the verifier-sampled pair only ran when a
reference source was supplied, recorded novel rows were checked only if
any existed, and nothing required the artifact to carry one at all — a
replay-only echo-table client with zero novel rows reached PROVEN.

Fix (`scripts/replay_equivalence.py`): `admission_errors` now ends with
the recorded-row floor (`NO_NOVEL_ROW_REFUSAL`): at least one
`novel_input`-flagged pair is REQUIRED on EVERY admission, with or
without a reference source. Evidence:
- RED `test_admission_requires_a_recorded_novel_input_row` (echo-table +
  zero novel rows was admitted — `admission_errors == []`); now refused.
- RED `test_equivalence_verdict_requires_novel_input_row` (the wired
  verdict face passed a runnable compute client with zero novel rows);
  now refused.
- The complicit `test_armed_verdict_passes_with_valid_artifact`
  (tests/test_oracle_anchors.py) is re-pinned to the corrected contract:
  armed face passes with a runnable client AND a recorded novel-input
  pair (nonce domain grown to [0, 1, 2]; cap-05 keeps the covering array
  complete; cap-06 is the novel pair).
- Promotion-path fixtures in tests/test_replay_equivalence_172.py
  (`test_claim_with_valid_artifact_promotes`,
  `test_reproduction_question_verified_with_matched_artifact`) gained the
  required novel pair; the honest-miss fixtures keep their refusal via
  the floor reason (which names `matched`), so their assertions stand.

### B2 (blocking) — a recorded novel pair recording a MISS was admitted

The recorded-novel-row check compared recompute only against the recorded
`repro_output`, ignoring `ref_output` and the recorded `byte_equal` flag;
a schema-honest row (`ref_output="REAL-SOURCE-SIG"`,
`repro_output="garbage"`, `byte_equal=false`) with a client that
recomputes the recorded repro was admitted.

Fix: each recorded novel-input pair now verifies on every admission —
`byte_equal is True` AND the recomputed output equals BOTH the recorded
`repro_output` AND the recorded `ref_output`; the recorded miss is named
(`byte_equal=... — a recorded MISS is not a matched pair ...`) and the
reference/reproduction divergence is named fabrication. Evidence:
- RED `test_admission_refuses_recorded_novel_miss` (echo-table-plus-miss
  client; was admitted); now refused with both named reasons.
- RED `test_admission_refuses_novel_row_with_false_flag_despite_matching_outputs`
  (honest client, flag flipped false; was admitted); now refused.
- RED `test_equivalence_verdict_refuses_recorded_novel_miss` (the same
  MISS shape at the wired verdict face); now refused.

### Non-blocking fixes

1. Verifier-challenge entropy: `novel_input_pair` no longer hard-codes
   `random.Random(248)`; it accepts an injectable `rng` and defaults to
   `secrets.randbits`-seeded entropy (challenge cannot be pre-captured
   offline). Evidence: RED
   `test_novel_input_pair_rng_is_injectable_and_deterministic` (TypeError
   on the old signature); injectable + deterministic + default path all
   green.
2. `scripts/README.md` settle_by_need row: the false
   "lib(consumed by completion/verify paths)" claim is reworded
   truthfully to "lib, tests" with a note that the settle-path wiring is
   a follow-up.

### Repair-round evidence

- Targeted suites all green (248 passed):
  `test_reproduction_oracle_248.py test_oracle_anchors.py
  test_replay_equivalence_172.py test_declaration_scan.py
  test_comment_hygiene_lint.py test_deploy_manifest_783.py
  test_statusline_assembly_212.py test_statusline_v2_142.py`.
- `python3 scripts/deploy_manifest.py --write` regenerated the
  `scripts/replay_equivalence.py` sha.
- `python3 scripts/comment_hygiene_lint.py --root .` → clean (665 files).
- `openspec validate fix-248-reproduction-oracle` → exit 0; the spec
  delta's admission requirement now states the recorded-row floor, the
  recorded-novel-row verification (flag + both outputs), and the
  entropy-seeded/injectable sampling, with four new scenarios.

## Experiment evidence

Mock web-signer fixture (seed 248): replay-only submission CANNOT pass a
novel-input pair; closed-book client DOES pass; a near-miss md5-instead-of-
sha256 client is also caught. See `tests/test_reproduction_oracle_248.py`
novel-input tests.

## Pieces

1. **Intake pinning** — `scripts/oracle_anchors.py`: generation-language
   detection (怎么生成/怎么算/什么原理/如何构造/how is it computed/what algorithm)
   pins `verification_method: reproduction` for algorithm-class asks;
   REPLAY_ORACLE_METHODS admissibility splits by question class; weak
   observational selection refused with named reason.
2. **Admission closed-book** — `scripts/replay_equivalence.py`: artifact
   `reproduction_client` field; admission loads and executes the client on
   every captured pair (recorded != recomputed → fabrication refusal);
   verifier-sampled NOVEL-INPUT pair sampled from declared `variables`
   domains with a source-derived reference (interface/adapter — tests use a
   stub, no network).
3. **Settle by need** — `scripts/settle_by_need.py` (new): replay-observation
   evidence settles only input-contract needs; algorithm-class claims admit
   reproduction evidence only; mis-booked replay observations re-route to the
   input-contract claim and the algorithm claim stays open.

## Files changed

- `scripts/oracle_anchors.py`, `scripts/replay_equivalence.py` (modified)
- `scripts/settle_by_need.py` (new)
- `tests/test_reproduction_oracle_248.py` (new, 20 tests),
  `tests/test_oracle_anchors.py`, `tests/test_replay_equivalence_172.py` (extended)
- `scripts/README.md` (catalog row), `deploy-manifest.yaml` (regenerated),
  `openspec/changes/fix-248-reproduction-oracle/`

## Test evidence

- Targeted: 109 passed (new + touched suites).
- Registration gates: 119 passed (declaration scan, deploy lifecycle,
  statusline manifest, comment hygiene) after manifest `--write` + catalog row.
- Full suite: 6675 passed / 13 failed / 12 skipped — failure-by-failure
  disposition: `test_toolchain.py` android (pre-existing env, fails on clean
  HEAD), `test_env_drift_475` (host-state flaky, fails on clean HEAD),
  `heartbeat_durable_830` x2 (order-noise flaky: pass standalone with this
  tree), `test_tier_census` x2 (xdist-inherent: fails IDENTICALLY on clean
  HEAD under -n 4), and 6 registration failures FIXED in this pass (manifest
  sha, catalog row, comment-hygiene R1 rewrites).
- `openspec validate fix-248-reproduction-oracle` → exit 0.

## Deviations

- The question-need mapping is consumed via the existing primary-questions
  `need` vocabulary (issue #77-era field) — nothing new derived from user
  text beyond the generation-language detector (owner folk-in ruling kept).
- Reference-from-source channel is an adapter interface; the server/browser
  adapters are out of this card (tests stub the interface).
