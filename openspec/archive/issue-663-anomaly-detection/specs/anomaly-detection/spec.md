## ADDED Requirements

### Requirement: Anomaly scoring

The anomaly detector SHALL compute a score in `[0, 1]` for every PROVEN fact in `facts/_INDEX.md` against a baseline corpus, where the score is the maximum of three sub-scores (lexical rarity, semantic unusualness, path unusualness) per the design doc D1.

#### Scenario: Common API call, low anomaly
- **WHEN** fact records a widely-known API call (e.g., `BCryptGenerateSymmetricKey` for AES key generation) and the baseline corpus contains 100+ RE-library pattern docs
- **THEN** anomaly score is in `[0.0, 0.3]` and no `boundary_type: anomaly` is auto-promoted

#### Scenario: Rare syscall pattern, high anomaly
- **WHEN** fact records a direct syscall with non-standard args not present in any baseline pattern doc
- **THEN** anomaly score is in `[0.7, 1.0]` and the fact auto-promotes to a note with `boundary_type: anomaly`

#### Scenario: Baseline corpus missing
- **WHEN** the baseline corpus is empty or unreadable
- **THEN** `score_fact` returns `0.0` for every fact and `scan_anomalies` emits one `kunglao_log` warning `"anomaly: empty baseline corpus — anomaly detection disabled"`
- **AND** `scan_anomalies` returns `[]` (DRAIN stays clean)

#### Scenario: Cold-start with no prior samples
- **WHEN** the workspace is fresh and `~/.kunglao/samples/` does not exist
- **THEN** RE-library pattern docs still load as baseline; only the prior-samples source is empty (fail-open at the source level, not the scan level)

### Requirement: Anomaly surfaced in DRAIN stage

When `scan_anomalies` returns ≥ 1 anomaly, the convergence decision machine SHALL emit `ANOMALY_DETECTED` between `GLOBAL_CONTRADICTION` and `DRAIN_CLEAN` in the DRAIN stage, transitioning to `BLOCKED` (not `SATURATED`).

#### Scenario: Anomaly detected, not yet resolved
- **WHEN** `scan_anomalies` returns ≥ 1 anomaly
- **THEN** the DRAIN verdict is `BLOCKED` with reason naming each anomaly's `fact_id` and `score`

#### Scenario: No anomalies
- **WHEN** `scan_anomalies` returns `[]`
- **THEN** DRAIN proceeds to `DRAIN_CLEAN` (no anomaly-driven BLOCKED)

#### Scenario: Empty baseline + scan called
- **WHEN** baseline corpus is empty AND `scan_anomalies` is called
- **THEN** no `ANOMALY_DETECTED` event fires (fail-open — anomaly detection is informational, not blocking)

### Requirement: Boundary type extension

`VALID_BOUNDARY_TYPE` in `scripts/lint_facts.py` SHALL include `"anomaly"` alongside the existing nine values. `ACTIVE_SCHEMA_REV` SHALL be bumped from 1 to 2.

#### Scenario: Fact with boundary_type=anomaly passes lint
- **WHEN** a fact file declares `boundary_type: anomaly`
- **THEN** `lint_fact` does NOT error on the boundary_type value (it's in `EMPTY_GATE_TYPES` so an empty `promotion_gate` is correct)
- **AND** the schema-pin output reflects `active_schema_rev: 2`

#### Scenario: Existing fact with prior boundary_type still passes
- **WHEN** a fact file carries `boundary_type: contradiction` (or any other prior value)
- **THEN** `lint_fact` behavior is unchanged (the new value is additive; existing values keep their semantics)

### Requirement: Co-resident note on threshold exceedance

When `score_fact(fact) ≥ anomaly_threshold` (configurable via `analysis_state.txt`, default `0.7`), the fact SHALL auto-promote to a co-resident note with `boundary_type: anomaly`. The fact's own status (PROVEN / INFERRED / etc.) is unchanged — anomaly is an observation, not a verdict demotion.

#### Scenario: High-score fact auto-promotes to note
- **WHEN** fact `F012` has score `0.85` and `anomaly_threshold = 0.7`
- **THEN** a note is written to `notes/F012.md` with `boundary_type: anomaly`, `claim_id: C-NN` (inherited from fact), `score: 0.85`, `top_dimension: <lexical|semantic|path>`

#### Scenario: Threshold tunable
- **WHEN** `analysis_state.txt` declares `anomaly_threshold: 0.5`
- **THEN** `score_fact` comparisons use 0.5 (a fact at 0.6 now flags, whereas default threshold would not)

### Requirement: Backward compatibility

Existing facts with any prior `boundary_type` value SHALL continue to pass `lint_fact` without change. The DRAIN stage of `convergence_check` SHALL continue to fire `GLOBAL_CONTRADICTION` and `DRAIN_CLEAN` as before. No existing event predicate SHALL be removed or have its precedence changed.

#### Scenario: Workspace with no anomaly scan results
- **WHEN** a workspace's facts are all low-score (≤ 0.3) or baseline is empty
- **THEN** DRAIN verdict is `DRAIN_CLEAN` — the new event never fires

#### Scenario: Claim migration unchanged
- **WHEN** `claim_migrator` promotes a claim to PROVEN while an anomaly note exists for one of its facts
- **THEN** the promotion proceeds normally (anomaly is observation, not demotion); no STAMP downgrade triggered by anomaly alone
