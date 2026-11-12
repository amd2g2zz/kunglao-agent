## ADDED Requirements

### Requirement: Certified fact fixture freshness

The certified fact fixture SHALL set its creation and review dates to the current local calendar date when written.

#### Scenario: Fact generated on any current date
- **WHEN** a certified fact is generated on a given local calendar date
- **THEN** its creation and review dates equal that date and the fact is not stale under the fact linter

#### Scenario: Review date exceeds the staleness threshold
- **WHEN** the current date is more than the linter's staleness threshold after a certified fact's review date
- **THEN** the fact linter reports `STALE_LAST_REVIEWED`
