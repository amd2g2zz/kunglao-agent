# Spec Delta — evidence-index
## ADDED Requirements
### Requirement: Evidence index registry
A workspace has an evidence index (evidence/_index.json authoritative + _INDEX.md generated) registering all raw evidence files (evidence/ + analysis_artifacts/) with eid, complete path, sha256, size, type. Derivations (summary.json/correlated.json/verdict.json) are excluded — they are computations from raw, not evidence.
#### Scenario: raw evidence registered, derivations excluded
- WHEN build_index scans a workspace with raw captures + summary.json + verdict.json
- THEN raw captures/traces/dumps in index; summary.json/verdict.json excluded
#### Scenario: eid path resolves and sha256 matches
- WHEN an index entry is read
- THEN its path resolves to an existing file AND recomputed sha256 matches
#### Scenario: empty workspace
- WHEN build_index runs on a workspace with no evidence/
- THEN empty index, no crash
