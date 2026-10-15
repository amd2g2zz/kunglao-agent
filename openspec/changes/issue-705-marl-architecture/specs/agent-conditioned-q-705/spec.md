# agent-conditioned-q-705 delta — issue-705-marl-architecture

## ADDED Requirements

### Requirement: The arm key carries an optional agent dimension

The arm key SHALL append `agent_type` as a fifth `|`-separated segment
when it is a non-empty token. Concretely
`arm_key(method_family, context_recipe, verification_mode, tier,
agent_type=None)`; a falsy `agent_type` SHALL produce the exact
four-segment key the pre-#705 surface produced (the determinism wall).
`agent_of_action` SHALL return the fifth segment for a 5-dim key and
`None` for a legacy key.

#### Scenario: a typed agent produces a 5-dim key

- **WHEN** `arm_key("strings-first", "facts_snapshot", "none", 1,
  "analyst")` is called
- **THEN** the result is `"strings-first|facts_snapshot|none|1|analyst"`

#### Scenario: the untyped agent keeps the legacy key byte-identical

- **WHEN** `arm_key("strings-first", "facts_snapshot", "none", 1)` is
  called with no agent type
- **THEN** the result is `"strings-first|facts_snapshot|none|1"` — the
  exact pre-#705 string

### Requirement: Different agent types address different Beta cells

`cell_posterior` SHALL address the querying agent's own cell as local
mass, and SHALL leave every other agent's mass at the same family in the
leave-one-out anchor (capped by SHRINK_CAP). Given observation rows
recorded at 5-dim arm keys, two agent types with different evidence SHALL
therefore yield different `(alpha, beta)` for the same signature and
family.

#### Scenario: agent A's evidence does not become agent B's local mass

- **WHEN** agent `analyst` has banked successes at
  `hypothesis-falsification|facts_snapshot|none|1|analyst` and agent
  `verifier` queries the same family at the same signature
- **THEN** the `analyst` cell's posterior differs from the `verifier`
  cell's, and the verifier's alpha/beta reflect inherited anchor mass,
  not the analyst's local counts

### Requirement: The legacy arm key folds unchanged

Rows recorded without an agent type SHALL fold into the same cells they
folded into before #705. The 5-dim read path SHALL NOT pool a same-arm
4-dim cell into local mass (it stays anchor mass).

#### Scenario: a 4-dim row folds at its legacy cell

- **WHEN** a settlement row carrying the 4-dim arm key
  `family|recipe|verif|tier` is folded
- **THEN** its credit lands in the cell keyed by that exact string
