## ADDED Requirements

### Requirement: PQ-coverage verdict reads task_spec and claim-register

The verdict-scorer agent SHALL read `task_spec.yaml` (specifically `primary_questions[]`) and `claim-register.yaml` to determine which primary questions have been answered by PROVEN facts. It SHALL NOT perform threat classification, attribution, or any maliciousness scoring.

#### Scenario: All primary questions answered by PROVEN facts
- **WHEN** task_spec declares primary_questions [q1, q2] and claim-register has claims with answers_question=q1 status=PROVEN and answers_question=q2 status=PROVEN
- **THEN** verdict-scorer marks both questions as `answered: true` in `analysis_verdict.primary_questions[]`

#### Scenario: Primary question with no answering claim
- **WHEN** task_spec declares primary_question q3 but no claim in claim-register has answers_question=q3
- **THEN** verdict-scorer includes q3 in `analysis_verdict.unresolved[]` with `answered: false` and sets `analysis_verdict.complete: false`

### Requirement: Confidence band enforcement mirrors convergence C0a/C0b

The verdict-scorer SHALL enforce confidence band requirements that are never more lenient than the convergence check (C0a/C0b). For questions without `need: model_selection`, the answering fact MUST have `status: PROVEN` AND `confidence_band: PROVEN-FULL`. For questions with `need: model_selection`, the answering claim MUST have at least one terminal fact and the rest REFUTED/DEFERRED.

#### Scenario: Standard question requires PROVEN-FULL
- **WHEN** primary_question q1 has no `need: model_selection` and the answering fact has status=PROVEN but confidence_band=PROVEN-PARTIAL
- **THEN** verdict-scorer marks q1 as `answered: false` and includes it in `analysis_verdict.unresolved[]` with a gap explaining the confidence band mismatch

#### Scenario: model_selection question with one terminal
- **WHEN** primary_question q2 has `need: model_selection` and answering claims include one PROVEN fact and one DEFERRED claim
- **THEN** verdict-scorer marks q2 as `answered: true`

### Requirement: Cross-consistency contradiction detection

The verdict-scorer SHALL detect contradictions by consuming the output of `fact_contradiction_gate.py`. It SHALL NOT reimplement contradiction detection logic. When two PROVEN facts on the same topic exist without supersedes or CONFLICT resolution, the verdict-scorer SHALL report the contradiction.

#### Scenario: Contradiction reported by fact_contradiction_gate
- **WHEN** fact_contradiction_gate.py output indicates F012 and F045 contradict on the same topic with no supersedes resolution
- **THEN** verdict-scorer includes the contradiction in `analysis_verdict.contradictions[]` and sets `analysis_verdict.correct: false`

#### Scenario: No contradictions
- **WHEN** fact_contradiction_gate.py reports no conflicts
- **THEN** verdict-scorer sets `analysis_verdict.contradictions: []` and does not set `correct: false` solely due to contradictions

### Requirement: Output evidence/verdict.json with analysis_verdict schema

The verdict-scorer SHALL write `evidence/verdict.json` with the v11 schema containing `_meta`, `sample_sha256`, `analysis_verdict`, and `self_audit`. The `analysis_verdict` object SHALL contain `complete`, `correct`, `primary_questions[]`, `unresolved[]`, `contradictions[]`, and `degraded[]`.

#### Scenario: Fully correct and complete analysis
- **WHEN** all primary questions are answered by PROVEN-FULL facts and no contradictions exist
- **THEN** verdict.json has analysis_verdict.complete=true, analysis_verdict.correct=true, analysis_verdict.unresolved=[], analysis_verdict.contradictions=[]

#### Scenario: Degraded evidence
- **WHEN** some evidence files are missing or incomplete
- **THEN** verdict-scorer populates analysis_verdict.degraded[] with reason and affected_question for each degradation

### Requirement: Self-audit honesty block

The verdict-scorer SHALL include a `self_audit` block with `evidence_strength` (strong|mixed|weak), `ignored_evidence`, and `open_questions`. This preserves the fail-closed self-honesty convention from issue #78.

#### Scenario: Mixed evidence strength
- **WHEN** some primary questions have PROVEN-FULL answers but others have gaps
- **THEN** self_audit.evidence_strength is "mixed" and open_questions lists the gaps

### Requirement: Pure-local operation with no external API calls

The verdict-scorer SHALL operate purely locally, reading only files within the workspace. It SHALL NOT make any external API calls, network requests, or web fetches.

#### Scenario: No network activity
- **WHEN** verdict-scorer processes a workspace
- **THEN** no external API calls are made; only local file reads occur

### Requirement: Banned out-of-scope terminology

The verdict-scorer agent specification SHALL NOT contain any of the following terms: maliciousness, attribution, admiralty, diamond, ach, classification, named_actor, threat actor, APT. These capabilities are out of scope for kunglao-agent.

#### Scenario: Grep for banned terms returns zero matches
- **WHEN** searching agents/verdict-scorer.md for banned terms (case-insensitive)
- **THEN** zero matches are found

## REMOVED Requirements

### Requirement: 6-dimension maliciousness scoring
**Reason**: Out of scope for kunglao-agent -- it verifies RE analysis correctness, not threat classification.
**Migration**: Maliciousness scoring is removed entirely. No replacement within kunglao-agent.

### Requirement: Attribution via Admiralty+ACH+Diamond
**Reason**: Out of scope for kunglao-agent -- it does not perform threat attribution or actor naming.
**Migration**: Attribution is removed entirely. No replacement within kunglao-agent.

### Requirement: Sandbox detonation-harness confound table
**Reason**: The harness-confound table was specific to maliciousness scoring of sandbox behavior traces, which is no longer scored.
**Migration**: Not applicable -- maliciousness scoring is removed entirely.

### Requirement: S5 named-actor gate
**Reason**: Actor naming is out of scope.
**Migration**: Not applicable.

### Requirement: Precomputed inputs (feature-scores, admiralty-ledger, gate-check)
**Reason**: These precomputed inputs fed the maliciousness/attribution pipeline which is removed.
**Migration**: Not applicable.
