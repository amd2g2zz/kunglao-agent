# Spec Delta — phase6-digest-failure-registry

## ADDED Requirements

### Requirement: Mechanical cold-start digest

The orchestrator generates a 2-4KB six-section markdown digest mechanically (no LLM) from workspace state, replacing full progress.txt reads at cold start. Facts' unit fields are carried verbatim (numeric fidelity). New verified facts appear in the digest on rebuild (completeness).

#### Scenario: six sections present
- WHEN build_digest runs on any workspace (including empty)
- THEN the output contains head, sec_a, sec_b, sec_c, sec_d, sec_e, sec_f markers

#### Scenario: numeric fidelity
- WHEN a fact has unit="8-byte ELF slots=811; Ghidra 774"
- THEN both 811 and 774 appear verbatim in sec_c (no collapse to single number)

#### Scenario: completeness
- WHEN a new verified fact is added and build_digest reruns
- THEN the new fact id appears in the digest

#### Scenario: pure mechanical (no LLM)
- WHEN build_digest runs twice on the same workspace
- THEN the outputs are identical except the head timestamp

### Requirement: Structured failure registry

Failure memory is stored as structured YAML rules (when/then/anchor), emitted verbatim into digest sec_e. New rules prepend (lost-in-the-middle mitigation).

#### Scenario: structured rules in digest
- WHEN failure-registry.yaml has a rule {when: X, then: Y, anchor: Z}
- THEN sec_e contains "WHEN X → THEN Y | anchor: Z"
