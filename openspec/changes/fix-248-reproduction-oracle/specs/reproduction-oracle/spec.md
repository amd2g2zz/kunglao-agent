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
the selection with a reason naming the refused method, and the pre-write
validation (`validate_values`) SHALL refuse to land it. Only
interrogative forms classify: a declarative passive ("the signature is
computed server-side") SHALL NOT be classified as generation-language.
Acceptance-class goals keep the existing admissible set unchanged.

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

#### Scenario: declarative passive is not generation-language

- WHEN the goal is "the signature is computed server-side" or
  "check the output is generated within 100ms"
- THEN `is_generation_language` is false (bare passive substrings are
  not markers; only interrogative forms classify)

#### Scenario: weak selection never lands for an algorithm-class goal

- WHEN `validate_values` is called with a generation-language
  `goal_verbatim` and `verification_method: replay-evidence`
- THEN it raises ValueError with a reason containing `replay-evidence`
- AND the same values with `verification_method: reproduction` land
  unchanged

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

#### Scenario: unknown evidence class fails closed

- WHEN evidence of an unrecognized class is cited by any claim
- THEN `settle_attempt` returns settled=false and the claim stays open
