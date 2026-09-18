# obstacle-ladder delta — issue-234-obstacle-ladder

## ADDED Requirements

### Requirement: Target/attack-surface ladder vocabulary (#234)

The system SHALL provide a 3-level target/attack-surface ladder
(T1/T2/T3) whose rungs are mechanism families enumerated per obstacle
class; levels SHALL be mechanism-family distinct by construction; a walked
ladder containing two rungs of the same family SHALL be invalid;
instrument availability SHALL annotate rungs and SHALL NOT filter them;
an unknown obstacle class SHALL fall back to the generic enumeration
(the ladder is never unwalkable).

#### Scenario: interception-class enumeration

- **WHEN** an obstacle declares obstacle_class `interception`
- **THEN** the family enumeration is hooking, repackaging, ca-install,
  proxy-interposition

#### Scenario: same-family rungs invalid

- **WHEN** a ladder file records two attempts whose family is `hooking`
- **THEN** ladder_defects reports a family-repeat defect naming both levels

#### Scenario: unknown class falls back

- **WHEN** an obstacle carries an empty or unknown obstacle_class
- **THEN** the family enumeration is the generic fallback tuple and the
  ladder validates against it

### Requirement: Obstacle settlement exhaustion gate (#234)

An obstacle claim (origin: failure-obstacle) MUST NOT settle CONFIRMED
(register status PROVEN) unless its target ladder is walked-valid AND its
exhaustion inventory is non-empty AND every inventory entry has its minted
sibling claim. Rejection MUST carry the named `TARGET LADDER GATE` reason
and leave the register unmodified. REFUTED settlements MUST NOT be gated.
The gate MUST be enforced on BOTH PROVEN write faces: the formal
`claim_migrator` gate AND the hook-side register-change backstop
(`compare_register_change_proven_gate`) — a direct register edit bypassing
claim_migrator MUST be rejected on the hook face with the same named
reason (#15/#78 dual-face policy).

#### Scenario: direct register edit bypass rejected on the hook face

- **WHEN** an obstacle claim is flipped OPEN -> PROVEN by a direct
  claim-register.yaml edit with no walked ladder
- **THEN** the hook backstop reports the PROMOTION GATE violation carrying
  the TARGET LADDER GATE reason and post_check exits 2

#### Scenario: backstop silent on the ladder face when walked

- **WHEN** the ladder is walked-valid, inventory non-empty, siblings
  minted, and the same direct-edit occurs
- **THEN** the backstop's violations contain no TARGET LADDER GATE reason

### Requirement: Class authority is the claim, not the artifact (#234 review F2)

The authoritative obstacle_class SHALL be pinned on the parent obstacle
claim at promotion time (`failure_analysis_gate --obstacle-class`). The
ladder artifact MUST declare the same class; settlement and mint MUST
fail-closed on an unpinned claim class, an undeclared artifact class, or a
mismatch. The mechanism-family enumeration SHALL be keyed on the
claim-pinned class.

#### Scenario: artifact class tamper rejected

- **WHEN** a claim pinned `obstacle_class: interception` presents a ladder
  artifact declaring `obstacle_class: visibility` with a valid walk of the
  visibility pool
- **THEN** the settlement blocker names the class mismatch as a defect

#### Scenario: unpinned claim class rejected

- **WHEN** an obstacle claim without a pinned obstacle_class presents any
  ladder artifact
- **THEN** the settlement blocker names the missing pin as a defect

#### Scenario: single parse (no two-read seam)

- **WHEN** the settlement blocker runs with caller-supplied register text
- **THEN** the claim-register file is never read a second time — origin,
  class, and sibling checks all consume the one parsed snapshot (and
  without supplied text, exactly one file read serves the whole gate)

#### Scenario: CONFIRMED without ladder rejected

- **WHEN** claim_migrator moves an obstacle claim to PROVEN and
  runs/target-ladder-<claim>.yaml is absent
- **THEN** the migration is refused with a TARGET LADDER GATE reason naming
  the missing levels and the register is unchanged

#### Scenario: CONFIRMED with walked ladder passes

- **WHEN** the ladder covers T1..T3 with distinct families, the inventory
  is non-empty, and each entry has a minted sibling
- **THEN** the gate passes and the PROVEN gate chain proceeds unchanged

#### Scenario: REFUTED ungated

- **WHEN** claim_migrator moves an obstacle claim to REFUTED with no ladder
  file at all
- **THEN** no TARGET LADDER GATE rejection occurs

### Requirement: Inventory entries fan out into sibling claims (#234)

Each exhaustion-inventory entry SHALL auto-register one sibling claim with
origin `obstacle-alternative`, an `obstacle_for` edge to the parent obstacle
claim, an inherited `answers_question` when the parent carries one, and a
real claim_deps.yaml depends_on edge. Minting SHALL be idempotent per
(obstacle_for, ladder_family) — case-insensitive on the family. A minted
sibling SHALL be OPEN and therefore TS-samplable (priority_ratio.is_open).
Minting SHALL refuse (explicit refusal receipt, zero mutation) when the
parent claim does not exist, does not carry origin failure-obstacle, or its
ladder is not walked-valid — no siblings against ghost parents.

#### Scenario: mistyped parent id refused

- **WHEN** mint is invoked for a claim id absent from the register
- **THEN** nothing is minted, the register and claim_deps.yaml are
  unchanged, and the refusal names the missing parent

#### Scenario: mint registers actionable siblings

- **WHEN** mint_sibling_claims runs for an obstacle claim whose ladder
  inventory has two entries
- **THEN** two OPEN sibling claims exist with the three linkage fields and
  the strategy statement carries family + tried + failed_because

#### Scenario: re-mint is idempotent

- **WHEN** mint_sibling_claims runs twice on the same ladder
- **THEN** the second run creates no new claims

### Requirement: promotion_attempts has a live writer (3-strike) (#234)

The dispatch-failure path SHALL increment promotion_attempts on the
dispatched claim when a finished worker's terminal status is
failed/blocked/error, and at promotion_attempts >= 3 SHALL escalate the
claim to the charter MUST-ASK lane (blockers/must-ask-<claim>.md + the
`must_ask` event) WITHOUT flipping the status — the exhaustion standard
must reach the ask gate (find_ladder_exhaustion) as a live claim, not a
post-mortem DEAD one (review F6). DEAD remains the explicit
`dead_letter --mark` decision. The transcript fallback of the hook face
SHALL accept only the worker transcript's own closing `status:` line
(quoted/echoed fragments MUST NOT burn strikes), and the entry-missing
path SHALL warn when a claim dispatch was expected. The writer SHALL fail
open (never break the hook) and SHALL explicitly no-op terminal or missing
claims.

#### Scenario: failed dispatch increments

- **WHEN** post_check observes a finished worker whose last status token is
  `blocked` on claim C-5
- **THEN** C-5 promotion_attempts increases by 1

#### Scenario: three strikes escalate to must-ask, not DEAD

- **WHEN** promotion_attempts reaches 3 through dispatch failures
- **THEN** the claim status is UNCHANGED (non-terminal),
  blockers/must-ask-<claim>.md exists, and the `must_ask` event is
  emitted; no dead-letter artifact is written

#### Scenario: escalation artifact failure never raises

- **WHEN** the must-ask artifact write fails (OSError shape) at strike 3
- **THEN** the writer still returns, the strike is counted
  (promotion_attempts == 3), and the receipt reports
  must_ask.escalated=False with the reason

#### Scenario: quoted status fragment does not burn a strike

- **WHEN** the worker status file is missing and the transcript contains
  an embedded `status: failed` fragment but closes with `status: done`
- **THEN** promotion_attempts is unchanged

#### Scenario: done stays silent

- **WHEN** a finished worker's last status token is `done`
- **THEN** promotion_attempts is unchanged
