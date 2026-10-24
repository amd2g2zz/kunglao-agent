# phi-tree-economy-796 delta — issue-796-phi-tree-v2

## ADDED Requirements

### Requirement: Φ is decisive mass on the closure hypothesis tree

Φ's progress dim SHALL be the closure-hypothesis-tree mass: only nodes
with DECISIVE resolution evidence carry mass
(posterior × critical-path depth weight), the chain multiplier SHALL
live INSIDE Φ (adjacent decisively-resolved trunk nodes multiply the
deeper node's value — a Φ-term, never an additive settlement bonus),
and the sum SHALL saturate at a documented normalization cap. An
unresolved node SHALL carry zero Φ mass (uniform birth mass — adding
new nodes can never decrease Φ; only resolution or refutation moves
existing node mass).

#### Scenario: discovery does not dilute

- **WHEN** new unresolved hypotheses are filed into the tree
- **THEN** `tree_phi` is unchanged (adding nodes never moves mass) and
  no transition can bank a negative r_t from that addition

#### Scenario: the chain multiplier is a Φ-term

- **WHEN** a trunk node resolves while its trunk parent is already
  decisively resolved
- **THEN** the resulting Φ movement exceeds the sum of the same two
  nodes resolving in isolation (superlinear, computed inside Φ)

### Requirement: decisive-evidence gating

A node SHALL score mass only when its resolution evidence is a
mechanical witness (reproduction/replay ref) or an independent
referee's confirmation; worker-authored refutations SHALL never settle
decisive-resolution, and assertion-only flips SHALL settle NEUTRAL
(zero credit, machine-recorded).

#### Scenario: a worker-authored flip pays nothing

- **WHEN** a resolution transition carries only a worker-authored
  assertion as its evidence
- **THEN** the settlement row records band NEUTRAL with zero credit and
  the tree mass does not move

### Requirement: valuation and attribution ride together

Every credited `hypothesis/decisive-resolution` settlement row SHALL
carry BOTH the ΔΦ valuation AND the proposing-step attribution ref;
a row missing either SHALL be invalid (refused at write). ΔΦ SHALL be
computed from the machine-recorded tree state diff, never a model
opinion, and rows SHALL settle credit only at or above the documented
ΔΦ threshold.

#### Scenario: an unattributable resolution is refused

- **WHEN** a decisive resolution arrives with an empty step ref
- **THEN** the settlement is refused with ONE loud warn and no row
  banks

### Requirement: churn clawback against the escrowed attribution

Overturning a credited node (supersede or refutation of a node whose
decisive credit settled) SHALL claw back the escrowed credit against
the PROPOSING step, plus a documented churn penalty, making identity
churn net-negative. The clawback SHALL be executable only against an
escrowed attribution ref (no ref ⇒ refuse — the original credit could
not have settled), SHALL live in the signed negative ledger face
(sealed rows, never folded into the non-negative credit stream), and
SHALL mirror into the shared cross-task strategy store as a censored
row with negative phi_delta.

#### Scenario: the identity-churn chain is unprofitable

- **WHEN** a family claim is decisively credited, refined, then
  overturned by a supersede
- **THEN** the clawback row names the proposing step, the scenario's
  cumulative reward is strictly negative, and the mirror row rides the
  shared store censored

### Requirement: elimination credit is small and saturating

A well-formed failed attempt SHALL eliminate a live candidate for
small positive credit, saturating over repeated same-shape attempts on
the same hypothesis, and SHALL require the same decisive-evidence gate
(planting candidates to refute them pays nothing).

#### Scenario: repeated same-shape failures saturate

- **WHEN** the same candidate shape is eliminated repeatedly against
  one hypothesis
- **THEN** each repeat's credit is strictly smaller than the previous
  and the total converges below the first decisive resolution's credit

### Requirement: the Φ swap stays potential-based and regime-stamped

`incremental_reward.potential` SHALL replace the dilution-dominated
facts term with the tree Φ (oracle dim unchanged and still gated by the
learning seal); the potential-based property SHALL hold (reward is a
potential difference), and every transition row SHALL stamp its
`phi_regime` version so the append-only ledger survives the Φ swap
without retroactive corruption.

#### Scenario: workspaces without a tree ride the oracle dim only

- **WHEN** a workspace has no hypotheses tree
- **THEN** the tree dim is honest-absent and Φ equals the legacy
  oracle-only renormalization, with the row stamped `phi-tree/1`

### Requirement: terminal settlement reconciles proxy against truth

When a claim reaches its terminal state, the economy SHALL run the
proxy-vs-truth reconciliation pass over that claim's attributed
resolution rows — recording the `(ΔΦ valuation, attribution, oracle
outcome)` calibration triples — and SHALL release the claim's escrows
(escrowed credit becomes warm-pool eligible only after release).

#### Scenario: oracle green releases and calibrates

- **WHEN** a claim closes oracle-green with escrowed resolution credit
- **THEN** a calibration row records each attributed row's ΔΦ against
  the oracle outcome and the escrows are marked released

### Requirement: the three-scenario replay ranks 3 > 2 > 1

Replaying the owner's three scenarios on a synthetic workspace SHALL
rank the total reward vectors scenario 3 (compounding critical-path
chain to an oracle-green closure) > scenario 2 (small monotone
incremental identification) > scenario 1 (identity churn, net
negative).

#### Scenario: the acceptance anchor

- **WHEN** the three scenarios are replayed through the public faces
  on a synthetic workspace
- **THEN** total_reward(3) > total_reward(2) > total_reward(1), with
  scenario 1 strictly negative and scenario 2 strictly positive
