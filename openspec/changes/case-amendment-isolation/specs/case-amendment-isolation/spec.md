## ADDED Requirements

### Requirement: Preserve successful concurrent posterior writes
All production updates to one workspace posterior SHALL serialize their read-modify-write interval. Concurrent reconciliations SHALL count a given transition once.

#### Scenario: Another process seeds a question during case correction
- **WHEN** reconciliation corrects a case and another process seeds an unrelated categorical question
- **THEN** the reopened snapshot contains both the corrected case posterior and the categorical question

### Requirement: Revoke only attributed derived knowledge
A committed case correction SHALL remove derived rows for the same workspace and claim, preserve ambiguous rows, and report unavailable attribution.

#### Scenario: Historical row lacks its origin
- **WHEN** a historical negative matches the amended claim ID but has a missing, legacy basename, or malformed workspace binding
- **THEN** reconciliation preserves its bytes, reports unavailable attribution and does not apply the amendment again on retry
