# Spec Delta — confidence-schema
## ADDED Requirements
### Requirement: ICD-203 7-tier probability ladder
confidence_schema.py defines a 7-tier confidence enum (almost_certain / very_likely / likely / roughly_even / unlikely / very_unlikely / almost_no_chance) with validate_confidence() accepting new values and legacy 3-tier values (confirmed / highly_likely / suspected) via automatic mapping.
#### Scenario: new 7-tier values accepted
- WHEN validate_confidence("almost_certain") is called
- THEN it returns "almost_certain" (valid)
#### Scenario: legacy 3-tier mapped to 7-tier
- WHEN map_legacy_confidence("confirmed") is called
- THEN it returns "almost_certain"
- WHEN map_legacy_confidence("highly_likely") is called
- THEN it returns "very_likely"
- WHEN map_legacy_confidence("suspected") is called
- THEN it returns "roughly_even"
#### Scenario: invalid confidence rejected
- WHEN validate_confidence("definitely") is called
- THEN it raises ValueError

### Requirement: BLIND REFUTE structured dissent recording
blind_gate.py records_dissent() writes a structured dissent block (verifier_id, finding, evidence_path, ts) when a BLIND verifier returns REFUTE. The dissent is appended to the fact file as a ```dissent yaml block.
#### Scenario: REFUTE produces dissent record
- WHEN record_dissent() is called with verifier_id, finding, evidence_path, and a fact path
- THEN a structured dissent block is appended to the fact file with all four fields
#### Scenario: CONFIRMED does not produce dissent
- WHEN the verifier verdict is CONFIRMED
- THEN no dissent block is written
