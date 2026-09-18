# plan-drift-detection delta — issue-237-b1o-gate-defects

## ADDED Requirements

### Requirement: In-progress credit for UNANSWERED_QUESTION (#237 D1)

The UNANSWERED_QUESTION drift class MUST fire only when NO claim of any
status answers the primary question directly AND no OPEN (non-terminal)
claim reaches a qid-answering claim through the claim_deps dependency chain
(transitive, cycle-safe). An OPEN chain working the question's
sub-questions is in-progress, not drift.

#### Scenario: mid-run OPEN chain does not fire

- **WHEN** a workspace has primary question q1, claim C-001 answering q1 at
  status OPEN, and OPEN sub-question claims (answers_question pq-*) whose
  claim_deps ancestors include C-001
- **THEN** plan_drift_detector exits 0 and reports no UNANSWERED_QUESTION

#### Scenario: no answerer and no chain still fires

- **WHEN** no claim in the register carries `answers_question: q1` and no
  open claim's dependency chain reaches a q1-answering claim
- **THEN** UNANSWERED_QUESTION is reported for q1 (exit 1, or 2 at 3+
  drifts)

### Requirement: Verifier dispatch pass-through (#237 D2)

The dispatch-gate drift blocker MUST NOT block a dispatch whose target agent
is a verifier-class agent (kunglao-redteam / verdict-scorer) for a PROVEN
claim; that dispatch is the remediation for the flagged UNVERIFIED_EVIDENCE
set. Non-verifier dispatches in the same drift state MUST still be blocked,
and the pass-through MUST leave an observable trace row.

#### Scenario: red-team dispatch on a flagged claim passes

- **WHEN** the workspace has 3+ drift (drift-severe, --auto exit 2) driven by
  PROVEN claims without verify records, and a dispatch targets
  kunglao-redteam for one of those PROVEN claims
- **THEN** dispatch_gate does not return the drift BLOCKED rc for that
  dispatch and a `drift_verifier_passthrough` row lands in the unified log

#### Scenario: worker dispatch stays blocked

- **WHEN** the same drift-severe workspace receives a kunglao-worker dispatch
  for the same claim
- **THEN** dispatch_gate returns the drift BLOCKED rc (2)

### Requirement: Verify-record provenance binding (#237 D3)

A `runs/verify-redteam-*.md` record MUST count toward UNVERIFIED_EVIDENCE
only when it survives the #827 content screen AND is corroborated by a
unified-log dispatch row that is hook-attributed (actor `hook:*`), names a
verifier-class agent in actor or detail, and carries the record's claim id.
Self-attested rows (worker:/verifier: actors) MUST NOT corroborate; missing
logs fail closed.

#### Scenario: self-minted record rejected (incident replay)

- **WHEN** a PROVEN claim carries a credible-content verify-redteam record
  and the unified log contains no dispatch rows for that claim (the
  2026-09-12 wbtest incident shape)
- **THEN** the detector still reports UNVERIFIED_EVIDENCE for the claim

#### Scenario: self-attested dispatch row does not corroborate

- **WHEN** the log row naming the verifier for the claim is written by the
  policed actor itself (actor `worker:kunglao-worker-1` or
  `verifier:kunglao-redteam`, not `hook:*`)
- **THEN** the record does not count and UNVERIFIED_EVIDENCE fires

#### Scenario: corroborated record accepted

- **WHEN** the unified log contains a `hook:worker_budget` dispatch row with
  `agent=kunglao-redteam` and the record's claim id, and the record passes
  the #827 content screen
- **THEN** the claim counts as verified and no UNVERIFIED_EVIDENCE is
  reported for it
