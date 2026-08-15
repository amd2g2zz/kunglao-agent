# Spec Delta — phase9-e2e-acceptance
## ADDED Requirements
### Requirement: End-to-end static acceptance
acceptance_check runs 5 post-refactor core checks (oracle 10/10, CLI 8/8, VoI formula, digest builds, test suite green) and reports overall pass/fail + per-check detail. Emits runs/e2e-acceptance-<ts>.json.
#### Scenario: overall pass on healthy repo
- WHEN acceptance_check runs
- THEN all 5 checks pass AND overall_passed is true
