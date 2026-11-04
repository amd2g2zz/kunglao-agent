# release-docs

## ADDED Requirements

### Requirement: readme-claims-match-code
A README claim about the shipped tree SHALL match that tree: a corpus that is
not committed is not "built-in", a key that carries four dimensions is not
described as one, and an arm ladder SHALL name every declared arm.

#### Scenario: corpus removed from version control
- **WHEN** a measurement corpus leaves the repository
- **THEN** the README says the corpus is operator-local before it quotes numbers from it

#### Scenario: arm count tracks the declaration
- **WHEN** `docs/design/ws5-five-arms.yaml` declares arms beyond the count the README names
- **THEN** the README is corrected to the declared set, including the arms that make the comparison falsifiable

### Requirement: readme-asset-text-match
An illustrative asset SHALL not contradict the mechanism the surrounding text
describes; where the asset shows a selection rule, it SHALL show sampling
rather than argmax, and its counts SHALL be grammatical.

#### Scenario: asset contradicts the text
- **WHEN** a GIF labels the chosen option "highest odds — first pick" while the section explains sampling
- **THEN** the asset is rebuilt before the section ships
