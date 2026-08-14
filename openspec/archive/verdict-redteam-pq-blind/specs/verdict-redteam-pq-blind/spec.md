### Requirement: verdict-redteam blind-verifies PQ coverage, not classification

#### Scenario: agent markdown contains BLIND invariant
- GIVEN `agents/verdict-redteam.md` exists
- WHEN parsed as text
- THEN it MUST contain the phrase "WITHOUT reading" (case-insensitive)
- AND it MUST reference "verdict.json" in the BLIND constraint section

#### Scenario: agent markdown contains no banned terms
- GIVEN `agents/verdict-redteam.md` exists
- WHEN searched for "maliciousness" or "attribution" (case-insensitive)
- THEN zero matches are returned

#### Scenario: agent markdown frames scope as PQ coverage
- GIVEN `agents/verdict-redteam.md` exists
- WHEN parsed as text
- THEN it MUST reference "primary_questions" or "primary questions" or "coverage"
- AND the output schema MUST contain "coverage" or "overall" field

#### Scenario: CONFIRMED/REFUTED/DIFF semantics preserved
- GIVEN `agents/verdict-redteam.md` exists
- WHEN parsed as text
- THEN it MUST mention "CONFIRMED" and "REFUTED" and "DIFF"
