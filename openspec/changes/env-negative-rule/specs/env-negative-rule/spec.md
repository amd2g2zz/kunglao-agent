# Spec Delta — env-negative-rule

The spec-delta format is `## ADDED Requirements` (this change introduces a new
capability `env-negative-rule`; it does not modify an archived spec —
`openspec/specs/` does not yet exist, so there is no base requirement to
MODIFY). The capability specializes the `inference-claim-blind-scope` gate
(#48) for environmental negative evidence; design.md carries the
gap-assessment evidence and the complementarity proof.

## ADDED Requirements

### Requirement: Environmental negative evidence under a self-reported env fault SHALL NOT establish a routing OR existence conclusion

When a claim's fact text contains an **environmental-negative-evidence basis** — `0 hits`, `0 occurrences`, `no call captured`, `no calls observed`, 无调用捕获, or 未触发 — AND an **environmental-fault self-report** (`stalled`, `never reconnected`, `reconnect`, `未触发`, `timeout`), the claim SHALL NOT be promoted to PROVEN on the dynamic miss alone. A routing conclusion ("not on the inject path", "routing correction") OR an existence conclusion ("does not exist", "absent", "not present") drawn from that miss SHALL be rejected (effective STAMP) unless the `verifier_sign_off` carries independent static evidence (`xref`, `disasm`, `decompile`, `capstone`, `ghidra`, `ida`, `call graph`, `callsite`). The rejection reason SHALL name the environmental-evidence problem explicitly (not the generic byte-anchor-coverage message). This is the specialization of `failure_analysis_gate`'s "failed attempt != negative result" three-question mechanism to environmental dynamic misses.

#### Scenario: existence claim from "no call captured" under env fault (F040 generalized)

- **WHEN** a claim states "Function X does not exist in the binary" and its fact text says "no call captured for X across the trace" and the provenance self-reports "debuggee WSS reconnect stalled; never reconnected", and the sign-off carries no static xref
- **THEN** `check_inference_blind_scope` returns not-allowed, effective STAMP, with a reason naming environmental negative evidence

#### Scenario: routing claim from "0 hits" under env fault (F040 regression — already covered by #48, asserted here as acceptance #2)

- **WHEN** a claim states "HandleCommand NOT on the inject path (0 hits)" and its provenance self-reports "WSS reconnect goroutine stalled; never reconnected", sign-off byte-anchor only
- **THEN** the check returns not-allowed, STAMP, reason naming environmental evidence

#### Scenario: environmental negative evidence WITH independent static xref passes

- **WHEN** the same env-faulted dynamic-miss fact additionally carries an independent static xref / disasm / call-graph trace in the sign-off
- **THEN** the check passes (PROVEN allowed) — static evidence replaces the dynamic-miss conclusion

#### Scenario: dynamic miss WITHOUT env fault is not blocked by this rule

- **WHEN** a routing claim's fact says "0 hits" but the provenance does NOT self-report any env fault, and the sign-off carries independent static xref
- **THEN** the static-evidence branch passes the claim (the env-negative rule does not fire; ordinary inference-scope coverage governs)

### Requirement: NEGATIVE-existence conclusions SHALL be treated as inferential claims

A claim whose statement or fact text (first 4000 chars) carries a NEGATIVE-existence conclusion — `does not exist`, `absent`, `not present`, 不存在, 未发现 — SHALL be treated as inferential (same scope as routing/causal patterns), so that it reaches the environmental-negative-evidence diagnostic and the independent-static-evidence requirement. A purely positive existence claim ("Foo exists at 0x401000") is NOT flagged by this rule.

#### Scenario: "absent" conclusion reaches the env-fault diagnostic

- **WHEN** a claim states "Function X is absent from the call graph" and its fact text says "no calls observed to X" plus an env-fault self-report, sign-off byte-anchor only
- **THEN** the check returns not-allowed, STAMP (the claim is NOT short-circuited as "non-inferential")

#### Scenario: positive existence claim is not over-flagged

- **WHEN** a claim states "Function Foo exists at 0x401000" with no NEGATIVE-existence pattern and no dynamic-miss basis
- **THEN** the inference-scope requirement does not apply; the existing BLIND byte-anchor gate governs

### Requirement: The generalized rule SHALL be enforced via the existing check_inference_blind_scope gate and its existing wire points

The generalized environmental-negative-evidence rule SHALL be implemented inside `scripts/blind_gate.py::check_inference_blind_scope` (the #48 gate). No new gate function, hook, or wire point SHALL be added: the rule reuses the gate already wired into `scripts/kunglao_record.py::claim_migrator` (PROVEN branch) and `hooks/worker_budget.py::compare_register_change_proven_gate`. This requirement is the complementarity contract with #48 — the two changes share one gate, not two.

#### Scenario: existence claim rejected at the claim_migrator wire point

- **WHEN** the orchestrator migrates an existence claim ("X does not exist", fact text "no call captured" + env fault, byte-anchor sign-off) to PROVEN
- **THEN** the register records STAMP and the migrator message includes the INFERENCE-gate reason

### Requirement: The env-negative rule SHALL be documented in the failure-modes reference

The rule SHALL be recorded in `references/failure-modes-monitoring.md` (F8 family — self-confident false PROVEN), with a one-line pointer added to the index in `references/failure-modes.md`. The entry SHALL cross-reference #48 (complementary inference-scope gate) and `scripts/failure_analysis_gate.py` (the three-question "failed attempt != negative result" mechanism that this rule specializes).

#### Scenario: doc entry exists and is discoverable

- **WHEN** a reader loads `failure-modes-monitoring.md` looking for false-PROVEN evidence-discipline rules
- **THEN** the env-negative rule is present, names the F040 incident, the trigger vocabulary (BP 0 hits / no call captured under env-fault), the forbidden conclusions (routing/existence), and the enforcement gate (`check_inference_blind_scope`)
