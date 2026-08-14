## ADDED Requirements

### Requirement: Inferential claims MUST be BLIND-signed with independent static evidence

A claim is **inferential** when its statement or fact text contains inferential/routing/causal patterns: `routing`, `route`, `not on ... path`, `correction`, `corrects F<NN>`, `gate`, or `0 hits`/`0 occurrences` used as path evidence. For inferential claims, the `verifier_sign_off` MUST cover the inference itself — its evidence (`evidence_path` / `refute_attempt` / `finding`) MUST contain at least one independent static-evidence marker (`xref`, `disasm`, `decompile`, `capstone`, `ghidra`, `ida`, `call graph`, `callsite`) and MUST NOT rely on `orchestrator-captured` evidence. A byte-anchor-only sign-off (string counts, byte hashes) is insufficient for routing/inference conclusions. Violation downgrades PROVEN to STAMP.

#### Scenario: routing claim signed off with orchestrator-captured evidence
- **WHEN** a claim states a routing conclusion ("HandleCommand NOT on inject path") and its sign-off evidence says the live disasm was orchestrator-captured
- **THEN** `check_inference_blind_scope` returns not-allowed, effective STAMP

#### Scenario: routing claim with independent static xref
- **WHEN** a routing claim's sign-off references an independent static xref/disasm trace (e.g., "xref at 0x3809A0 shows func12 called from HandleCommand dispatch")
- **THEN** the check passes (PROVEN allowed)

#### Scenario: pure byte-anchor claim
- **WHEN** the claim statement and fact text contain no inferential patterns (e.g., "13 ASCII strings in .rdata")
- **THEN** the inference-scope requirement does NOT apply; the existing BLIND gate governs

### Requirement: Environmental negative evidence MUST NOT establish routing

When the fact text contains a negative-hit pattern (`0 hits`, `0 occurrences`) AND an environmental-fault self-report (`stalled`, `never reconnected`, `未触发`, `timeout`), the claim SHALL NOT be PROVEN on dynamic-miss evidence alone — independent static xref evidence is mandatory. The rejection reason MUST identify the environmental-evidence problem explicitly.

#### Scenario: 0-hits + stalled debuggee, no static xref (F040)
- **WHEN** the fact says "HandleCommand @0x3809A0 NOT on inject path (0 hits)" and its provenance self-reports "WSS reconnect goroutine stalled... never reconnected", and the sign-off carries no static xref
- **THEN** the check returns not-allowed with a reason naming the environmental negative evidence; the claim stays STAMP and cannot enter a report as routing fact

#### Scenario: 0-hits + env fault WITH static xref
- **WHEN** the same 0-hits/env-fault fact additionally carries an independent static xref in the sign-off
- **THEN** the check passes (the static evidence replaces the dynamic-miss conclusion)

### Requirement: claim_migrator SHALL downgrade PROVEN when the inference scope is not covered

`scripts/kunglao_record.py::claim_migrator` SHALL run `check_inference_blind_scope` in its PROVEN branch (alongside the BLIND and CONFLICT gates). On failure the effective status SHALL be STAMP and the message SHALL include the inference-scope reason.

#### Scenario: promotion of an uncovered routing claim
- **WHEN** the orchestrator migrates an inferential claim to PROVEN whose sign-off lacks independent static evidence
- **THEN** the register records STAMP and the message names the inference-scope failure

### Requirement: register-write backstop SHALL block inferential PROVEN without scope coverage

`hooks/worker_budget.py::compare_register_change_proven_gate` SHALL extend its newly-PROVEN check with the inference-scope gate (reusing the register text it already reads), so direct register writes are also blocked.

#### Scenario: orchestrator direct write of an uncovered routing claim
- **WHEN** the orchestrator writes PROVEN directly to the register for an inferential claim without independent static evidence
- **THEN** the backstop rejects the write with the inference-scope reason
