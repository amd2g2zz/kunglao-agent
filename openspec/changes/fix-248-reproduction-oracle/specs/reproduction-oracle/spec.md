# Spec Delta — fix-248-reproduction-oracle

## ADDED Requirements

### Requirement: Intake maps generation-language to the reproduction oracle

The system SHALL derive the verification method from the verbatim goal
(users speak folk — #170/#174 lineage); the user is never asked to know
replay/reproduction vocabulary. A goal containing generation-language
(怎么生成 / 怎样生成 / 如何生成 / 怎么算 / 如何计算 / 什么原理 / 什么算法 /
如何构造 / how is it computed / what algorithm / how is it generated /
how is it constructed, and the interrogative+computation-verb pattern)
SHALL be classified as an algorithm-class question and SHALL pin
`verification_method: reproduction`, overriding any weaker selection.
For an algorithm-class goal the observational methods (`replay-evidence`,
`static`, `manual`) SHALL NOT be selectable: the intake gate SHALL refuse
the selection with a reason naming the refused method. Acceptance-class
goals keep the existing admissible set unchanged.

#### Scenario: generation-language goal pins reproduction

- WHEN task_spec carries `goal_verbatim: "签名参数是怎么生成的"` with
  `verification_method: replay-evidence`
- THEN `derive_verification_method` returns `reproduction`
- AND `intake_method_gate` returns not-ok with a reason containing
  `replay-evidence` and the algorithm-class refusal

#### Scenario: acceptance-language goal keeps replay-evidence selectable

- WHEN task_spec carries an acceptance-class goal ("登录接口能返回 200")
  with `verification_method: replay-evidence`
- THEN `intake_method_gate` returns ok with an empty reason

#### Scenario: English generation-language is detected

- WHEN the goal is "how is the signature computed" or
  "what algorithm generates the token"
- THEN `is_generation_language` is true (interrogative + computation-verb
  word pattern; adjacency not required)

### Requirement: Admission executes the reproduction client closed-book with verifier-sampled novel inputs

The replay artifact schema SHALL gain a `reproduction_client` field: a
workspace-relative path loadable by the existing
`oracle_runner.load_client`. Admission SHALL refuse an artifact without a
runnable client (the copy-both-sides artifact — ref_output ==
repro_output == browser-captured signatures, no client — that passed
before). Admission SHALL load and EXECUTE the client on every captured
pair; recomputed output != recorded `repro_output` SHALL be refused with
the FABRICATION reason, and the mutation gate SHALL run on the recomputed
rows (silent-green oracle refusal). Additionally admission SHALL require
at least one NOVEL-INPUT pair. The recorded-row path is the structural
floor and runs on EVERY admission: an artifact whose pairs are all
captured-parameter rows (zero recorded novel-input pairs) SHALL be
refused even when a runnable client reproduces every captured row —
captured-parameter replay alone cannot witness the algorithm. The floor
is NOT forgeable by relabeling: a recorded novel-input pair SHALL be
verified doc-locally on every admission — its `input_id` SHALL sit
outside `captured_inputs` (a novel input is not a captured one) and its
core assignment (projection onto the declared `variables`) SHALL differ
from every captured row's core; violations SHALL be refused with the
named `not fresh` reasons. The schema membership rule SHALL match: a
`novel_input` pair is exempt from the captured-inventory requirement
(novelty outside the capture inventory is expressible) and a
`novel_input` pair whose id is inside `captured_inputs` SHALL be refused
by the lint with the same reason. The verifier-sampled live pair is the
stronger face where a `reference_source` adapter is available: the
verifier samples a fresh combination from the artifact's own declared
`variables` domains (not any captured row's core assignment; fixed
parameters carry over), obtains the reference output FROM THE SOURCE
through the adapter interface (server submit or browser debug-anchoring
in production — the judge's privilege; stub in tests), and requires the
closed-book reproduction to match byte-for-byte. The sampling SHALL be
seeded from verifier entropy (`secrets`-derived) with the rng injectable
so tests can pin the sample; a fixed constant seed is refused by review.
A captured-parameter replay submission structurally cannot pass a
novel-input pair.

#### Scenario: artifact without runnable client is refused

- WHEN the artifact records ref_output == repro_output ==
  captured signatures and has no `reproduction_client`
- THEN `admission_errors` refuses with a reason containing
  `reproduction_client`

#### Scenario: recomputed output differing from the recorded output is fabrication

- WHEN the declared client exists and re-executes on a captured pair but
  recomputes an output different from the recorded `repro_output`
- THEN `admission_errors` refuses with a reason containing `fabrication`

#### Scenario: artifact with zero recorded novel-input rows is refused

- WHEN the artifact carries a runnable `reproduction_client` that
  recomputes every captured row, but no pair is flagged
  `novel_input`
- THEN `admission_errors` refuses with a reason containing
  `no recorded novel-input pair`
- AND the wired verdict face (`equivalence_verdict` via
  `check_claim_admission` and the unverified-PQ face) refuses the claim,
  so a replay-only echo-table submission cannot reach PROVEN

#### Scenario: a relabelled captured row cannot satisfy the novel floor

- WHEN a `novel_input` pair's `input_id` is declared in
  `captured_inputs` (a captured row relabeled by the submitter), or its
  core assignment over the declared variables duplicates a captured
  row's core
- THEN the schema lint refuses with a reason containing `not fresh`
- AND `admission_errors` refuses on every admission with the same named
  reason, at both wired faces (`check_claim_admission`, the
  unverified-PQ face) — the flag alone forges nothing

#### Scenario: a novel pair outside the capture inventory is schema-valid

- WHEN a `novel_input` pair's `input_id` is NOT declared in
  `captured_inputs` and its inputs stay inside the declared domains
- THEN the schema lint passes it (novelty is expressible) and admission
  judges it by the freshness and record checks above

#### Scenario: recorded novel-input pair recording a MISS is refused

- WHEN a `novel_input` pair records `byte_equal: false` (a recorded
  MISS), or the client's recomputed output equals the recorded
  `repro_output` but differs from the recorded `ref_output`
- THEN `admission_errors` refuses with a reason naming the recorded miss
  (`byte_equal`) and the reference/reproduction divergence
  (`fabrication`) — the recomputed output must equal BOTH recorded
  outputs and the recorded flag must be True

#### Scenario: replay-only submission cannot pass a novel-input pair

- WHEN the reproduction client is an echo table of captured signatures
  and the verifier samples a NOVEL input, obtaining the reference from
  the source adapter
- THEN the closed-book reproduction of the novel input does not match the
  source-derived reference (`byte_equal` is false)
- AND `admission_errors` refuses with a reason containing `novel`

#### Scenario: closed-book client passes honest admission including the novel pair

- WHEN the reproduction client implements the reversed algorithm and the
  artifact carries a captured-face plus a novel-input pair whose
  reference is source-derived
- THEN `admission_errors` returns no errors

#### Scenario: verifier challenge is entropy-seeded and injectable

- WHEN `novel_input_pair` is called without an explicit rng
- THEN the sampling is seeded from `secrets`-derived verifier entropy
  (not a fixed constant)
- AND an explicit `rng` argument pins the sample deterministically for
  tests

### Requirement: Evidence settles by need

Evidence admissibility SHALL be decided by the claim's question `need`
field (primary_questions vocabulary). Acceptance-side observations
(`replay-observation` evidence class) SHALL settle only input-contract /
param-sufficiency claims (`need: yes_no_with_evidence`). Generation-side
propositions (algorithm-class needs, e.g. `model_selection`,
`protocol_description`) SHALL admit `reproduction` evidence only. A
replay observation cited by an algorithm-class claim SHALL NOT settle it:
the claim SHALL stay open and the observation SHALL be re-routed to the
input-contract claim. Unknown evidence classes fail closed.

#### Scenario: replay observation does not settle an algorithm-class claim

- WHEN a `replay-observation` is cited by a claim whose question need is
  `model_selection`
- THEN `settle_attempt` returns settled=false, claim_stays_open=true,
  and reroute_to=`input-contract`

#### Scenario: reproduction evidence settles the algorithm claim

- WHEN `reproduction` evidence is cited by a claim whose question need is
  `model_selection`
- THEN `settle_attempt` returns settled=true, claim_stays_open=false

#### Scenario: replay observation settles an input-contract claim

- WHEN a `replay-observation` is cited by a claim whose question need is
  `yes_no_with_evidence`
- THEN `settle_attempt` returns settled=true with no re-route
