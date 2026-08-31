# capability-registry delta — #751

## MODIFIED Requirements

### Requirement: closed capability vocabulary
The system SHALL route on a closed `<domain>:<operation>` vocabulary held in
tools/validate_index.py `_CAPABILITY_TAGS`; every `produces` tag in
tools/_INDEX.yaml SHALL be a member.

#### Scenario: js semantic tags join the vocabulary
- **WHEN** gitnexus-query declares `js:semantic-query` and `js:call-graph`
  in its produces list
- **THEN** validate_index accepts the shipped index (tags are vocabulary
  members), preserving the Rule B deliberate-review contract for future adds

### Requirement: provider annotation block
Annotated entries SHALL carry provider / produces / requires / cost_hint /
quality where quality covers every produced tag (#692 schema).

#### Scenario: one gitnexus provider covers both domains
- **WHEN** the gitnexus-query entry produces android + js domain pairs
- **THEN** the entry stays single-provider with requires
  `[source_tree, gitnexus_index]`, and quality maps every produced tag to
  high; input_output documents that for the js domain source_tree is a
  wakaru/webcrack output directory registered as evidence `unpack_out`

#### Scenario: recovery tools declare the hand-off
- **WHEN** wakaru-unbundle or webcrack-deobfuscate completes on a target
- **THEN** their registry input_output text names the output-directory →
  `evidence/<run>.json` unpack_out registration so the lazy index knows the
  tree it can build from

## ADDED Requirements

### Requirement: post-recovery semantic indexing posture (web)
Web RE methodology SHALL place a semantic-index step between layered peeling
and parameter location: build the graph (`gitnexus analyze <out_dir>`) then
query chains (signature-string assembly → callees → request entry point)
instead of manual grep over the recovered tree.

#### Scenario: quickref carries the step
- **WHEN** the web RE quick reference layered-peeling section is read
- **THEN** an index-then-query step exists with the signature-trace query
  posture, English-only, execution details deferred to the worker contract

### Requirement: deterministic routing of signature-trace claims
Signature-tracing claims SHALL deterministically resolve js:semantic-query /
js:call-graph to the gitnexus-query tool chain, and the specialist trigger
contract for gitnexus-query intent (semantic/xref/call graph/调用链/谁调用
paraphrase family) SHALL be regression-pinned against a fixture table.

#### Scenario: claim routes through the resolved chain
- **WHEN** resolve_capability runs for "js:semantic-query" over the shipped
  registry
- **THEN** the concrete tool name is exactly [gitnexus-query]

#### Scenario: fixture-pinned specialist intent
- **WHEN** recommend_agent_type sees the claim "trace which function builds
  the signature string through the bundle" against the pinned trigger
  fixture
- **THEN** the recommendation is gitnexus-query, while today's shipped
  agent table still yields no false-positive specialist for the same claim
