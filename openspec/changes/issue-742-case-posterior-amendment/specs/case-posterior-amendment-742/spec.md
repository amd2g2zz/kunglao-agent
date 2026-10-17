# case-posterior-amendment-742 delta — issue-742-case-posterior-amendment

## ADDED Requirements

### Requirement: A corrected claim outcome amends its case pair

When a claim's CURRENT decisive register status disagrees with the
outcome already observed for its (case, claim) pair, the settle pass
SHALL apply the ±1 flip to the case posterior (belief-first, floored at
the Beta(1,1) support) and append ONE `case-amendment/1` audit row. The
original observation row SHALL stay byte-untouched.

#### Scenario: the flip reaches the belief exactly once

- **WHEN** a claim's register status flips across the decisive
  polarity after its pair was observed
- **THEN** one amendment row lands, the pair's posterior mass moves by
  the flip, and every re-run is a no-op

#### Scenario: the runner-banked mass survives

- **WHEN** the case carries extra accumulator mass banked by the
  offline runner face (no ledger rows)
- **THEN** the amendment applies the delta — the yaml is never
  recomputed from the row log

### Requirement: Honest gaps write nothing

A non-decisive terminal, a removed claim, a retired case, and an
unobserved pair SHALL NOT fabricate a correction.

#### Scenario: each gap writes nothing

- **WHEN** the reconcile runs under any of the gap conditions
- **THEN** no amendment row lands and no belief moves

### Requirement: The observation record stays history

The case-observation/1 rows SHALL remain byte-untouched by the
amendment face.

#### Scenario: append-only wall holds

- **WHEN** an amendment lands
- **THEN** every prior case-observation/1 row is byte-identical
