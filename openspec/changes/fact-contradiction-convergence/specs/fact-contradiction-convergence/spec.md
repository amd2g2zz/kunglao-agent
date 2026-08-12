## ADDED Requirements

### Requirement: Same-topic multi-PROVEN facts MUST carry a supersedes relationship or explicit CONFLICT

A topic is the set of facts sharing the same `claim_id` (from `facts/_INDEX.md`) or overlapping `sample_refs` (from fact frontmatter). When two facts in the same topic are both `PROVEN` and their conclusions differ (whitespace-normalized), at least one side MUST declare `supersedes:` / `superseded_by:` linking the pair, or the pair MUST be marked explicit CONFLICT — otherwise the promotion gate SHALL block and downgrade the effective claim status to STAMP (needs-resolution).

#### Scenario: F035/F040 routing contradiction (a2b5e25c)
- **WHEN** F035 and F040 are both PROVEN, share the same claim/topic, assert different routing conclusions, and neither declares `supersedes:`/`superseded_by:`
- **THEN** the contradiction gate reports CONFLICT naming both fact ids, and any attempt to promote a claim under that topic to PROVEN is blocked (effective status STAMP)

#### Scenario: supersedes link resolves the pair
- **WHEN** one of the pair declares `supersedes: F<other>` (or the other declares `superseded_by: F<first>`)
- **THEN** the pair is NOT a contradiction; the gate passes

#### Scenario: same topic, same conclusion
- **WHEN** two PROVEN facts share a topic and their conclusions are identical (whitespace-normalized)
- **THEN** the pair is NOT a contradiction (converged, not conflicting); the gate passes

#### Scenario: different topics
- **WHEN** two PROVEN facts have different claim_ids and disjoint `sample_refs`
- **THEN** the pair is NOT a contradiction; the gate passes

### Requirement: Empty or missing fact state MUST NOT crash the gate

The contradiction gate SHALL be a pure function that returns an empty conflict list when `facts/_INDEX.md` does not exist, contains no rows, or the facts directory is empty.

#### Scenario: fresh workspace
- **WHEN** the workspace has no facts or an empty index
- **THEN** `scan_conflicts` returns `[]` and `check_proven_contradiction` returns allowed

### Requirement: claim_migrator SHALL downgrade PROVEN on contradiction

`scripts/kunglao_record.py::claim_migrator` SHALL run the contradiction check in its PROVEN branch (alongside the BLIND gate). When a contradiction is detected, the effective status SHALL be STAMP and the reason SHALL name the conflicting fact pair.

#### Scenario: promotion attempt over an unresolved pair
- **WHEN** the orchestrator migrates a claim to PROVEN while two same-topic PROVEN facts with different conclusions lack a supersedes relationship
- **THEN** the register records STAMP instead of PROVEN, and the returned message names the CONFLICT pair

### Requirement: register-write backstop SHALL block PROVEN with contradictions

`hooks/worker_budget.py::compare_register_change_proven_gate` SHALL extend its newly-PROVEN check with the contradiction gate so that direct register writes (bypassing `claim_migrator`) are also blocked when the promoted claim's fact conflicts with another PROVEN fact in the same topic.

#### Scenario: orchestrator direct write
- **WHEN** the orchestrator (or any actor) writes PROVEN to the register for a claim whose fact is in a contradiction pair
- **THEN** the hook backstop rejects the write with the CONFLICT reason
