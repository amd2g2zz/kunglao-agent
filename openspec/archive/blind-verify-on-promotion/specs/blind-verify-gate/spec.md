# Spec Delta — blind-verify-on-promotion
## ADDED Requirements
### Requirement: PROVEN promotion requires independent BLIND verifier sign-off
A claim SHALL only be promoted to PROVEN when its fact file contains a valid `verifier_sign_off` block from an independent verifier (verifier_id MUST differ from the claim's worker_id, and MUST include refute_attempt + sign_off_at + verdict=CONFIRMED). Claims promoted to PROVEN without BLIND sign-off MUST be auto-downgraded to STAMP (claimed-but-unverified). A BLIND REFUTE verdict MUST also downgrade to STAMP. The orchestrator MUST NOT be exempt from this gate.
#### Scenario: PROVEN with valid BLIND sign-off
- WHEN claim_migrator is called with new_status=PROVEN and the fact file has a complete verifier_sign_off block (verifier_id, refute_attempt, sign_off_at, verdict=CONFIRMED)
- THEN the claim is promoted to PROVEN in the register
#### Scenario: PROVEN without BLIND sign-off auto-downgrades to STAMP
- WHEN claim_migrator is called with new_status=PROVEN and the fact file lacks a verifier_sign_off block
- THEN the claim is written as STAMP (not PROVEN) in the register, and the return message reports the downgrade
#### Scenario: BLIND REFUTE blocks PROVEN
- WHEN claim_migrator is called with new_status=PROVEN and the fact file's verifier_sign_off has verdict=REFUTE
- THEN the claim is written as STAMP (not PROVEN) in the register
#### Scenario: STAMP is non-terminal
- WHEN a claim has status STAMP
- THEN it may be subsequently promoted to PROVEN (after obtaining BLIND sign-off) or refuted
### Requirement: BLIND coverage measurement
A measurement tool SHALL read claim-register.yaml + facts/*.md and report the ratio of PROVEN claims that have valid BLIND verifier sign-off. The tool MUST exit 0 (measurement, not a gate).
#### Scenario: measure reports correct ratio
- WHEN the workspace has N PROVEN claims and M of them have valid verifier_sign_off blocks
- THEN measure_blind_coverage.py outputs proven=N, blind_signed=M, coverage=M/N
