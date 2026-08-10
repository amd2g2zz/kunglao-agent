# Spec Delta — convergence-completeness-gate
## ADDED Requirements
### Requirement: CONVERGED requires all primary_questions answered by PROVEN claims
When all claims are terminal and no partial facts remain, the convergence decision SHALL additionally verify that every primary_question in task_spec.yaml has at least one claim with answers_question == q.id and status == PROVEN. If any primary_question lacks a PROVEN answering claim (e.g. only STAMP, NEGATIVE, or no answering claim exists), the decision MUST NOT be CONVERGED — it SHALL downgrade to SATURATED with a diagnostic action message naming the unverified questions.
#### Scenario: all primary_questions PROVEN → CONVERGED
- WHEN all claims are terminal, no partial facts exist, and every primary_question has a PROVEN answering claim with zero orphan terminal claims
- THEN decide() returns CONVERGED with exit_code=0
#### Scenario: primary_question answered only by STAMP → NOT CONVERGED
- WHEN all claims are terminal, no partial facts exist, but a primary_question's answering claim has status STAMP (not BLIND-verified)
- THEN decide() returns SATURATED (not CONVERGED) with an action message naming the unverified question
#### Scenario: primary_question answered only by NEGATIVE → NOT CONVERGED
- WHEN all claims are terminal, no partial facts exist, but a primary_question's answering claim has status NEGATIVE (terminal but not PROVEN)
- THEN decide() returns SATURATED (not CONVERGED)
### Requirement: CONVERGED requires zero orphan terminal claims
A terminal claim (PROVEN, VERIFIED, NEGATIVE, REFUTED, DEFERRED) with no answers_question field is an orphan. When primary_questions exist in task_spec.yaml, the presence of orphan terminal claims SHALL block CONVERGED — the decision MUST downgrade to BLOCKED with a diagnostic naming the orphan claim IDs.
#### Scenario: orphan terminal claim blocks CONVERGED
- WHEN all claims are terminal, no partial facts exist, but a terminal claim has no answers_question and primary_questions are defined
- THEN decide() returns BLOCKED (not CONVERGED) with an action message naming the orphan claim IDs
#### Scenario: no primary_questions defined → orphan check skipped
- WHEN task_spec.yaml has primary_questions: [] (feature not used) and all claims are terminal
- THEN decide() returns CONVERGED regardless of answers_question presence (backward compat)
### Requirement: decide() output includes completeness diagnostics
The decide() return dict SHALL include orphan_claims (list of orphan terminal claim dicts) and unverified_primary_qs (list of question dicts with their answering claims) as fields, enabling downstream tooling to inspect completeness without re-deriving it.
#### Scenario: CONVERGED decision includes empty completeness fields
- WHEN decide() returns CONVERGED
- THEN the output dict contains orphan_claims=[] and unverified_primary_qs=[]
### Requirement: SPINNING flatline detection must not be hidden by same-turn dedup
The _dedup_consecutive function in convergence_health.py SHALL not collapse more than MAX_DEDUP_COLLAPSE (2) consecutive same-state entries, even when all entries are within the SAME_TURN_WINDOW_SEC time window. Additionally, SAME_TURN_WINDOW_SEC SHALL be 30 seconds (reduced from 120) — orchestrator turns called >30s apart represent separate evaluation cycles, not same-turn noise. This ensures real flatlines (same open_count across many minutes) are preserved for SPINNING/STALLED detection.
#### Scenario: 10 snapshots 60s apart trigger SPINNING
- WHEN 10 ledger snapshots with identical open_count are spaced 60 seconds apart
- THEN assess() returns verdict=SPINNING (not STALLED or HEALTHY)
#### Scenario: 3 snapshots 2s apart dedup to 1
- WHEN 3 ledger snapshots with identical state are spaced 2 seconds apart (genuine same-turn noise)
- THEN _dedup_consecutive collapses them to 1 entry
