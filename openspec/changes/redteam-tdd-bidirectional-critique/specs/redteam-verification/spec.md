# Spec Delta

## Purpose

Defines the red-team checker's evidence discipline: executable TDD evidence, independent reproduction, bidirectional round-trip verification, and the evidence bar for REFUTED verdicts.

## ADDED Requirements

### Requirement: TDD evidence is required for CONFIRMED
The checker MUST write an executable falsifier test RED before the claim can be GREEN, store it under `runs/rt-tests/<claim>/`, and record the executed command and the RED→GREEN transition. A verification record without this evidence MUST NOT be CONFIRMED. The only waiver is the mapping table's exception-allowed kinds (`cti_correlation`, `attribution`, `external_source`), which must declare `machine_check: none` with a claim kind and reason.

#### Scenario: Missing TDD evidence
- **WHEN** a checker record carries no `runs/rt-tests/<claim>/` artifact and no RED→GREEN log
- **THEN** the verdict is `UNVERIFIED-WITH-GAP`, not CONFIRMED, and the claim cannot promote

#### Scenario: RED→GREEN recorded
- **WHEN** the record carries the falsifier test, the failing RED run, and the passing GREEN run of the executed check
- **THEN** the verdict is eligible for CONFIRMED

### Requirement: Reproduction is executed, not read
The checker MUST execute the reproduction itself against the captured artifacts. Reading the rollout's narrative, status, or maker outputs is not reproduction and MUST NOT count as verification evidence.

#### Scenario: Read-only record
- **WHEN** a record cites only the rollout's own artifacts or narrative as its evidence
- **THEN** the record fails the reproduction requirement and the verdict cannot be CONFIRMED

#### Scenario: Executed reproduction
- **WHEN** the record carries a command the checker ran against captured inputs plus its actual output
- **THEN** the reproduction requirement is satisfied

### Requirement: Reversible claims require bidirectional round-trip
For reversible claims (decode, decrypt, encode, sign, replay), the checker MUST verify both directions and MUST establish byte-identity of the round trip on the captured pairs. One-way success MUST cap the verdict at `UNVERIFIED-WITH-GAP`.

#### Scenario: One-way success only
- **WHEN** the reverse direction reproduces the captured output but the forward direction is not executed or fails identity
- **THEN** the verdict is `UNVERIFIED-WITH-GAP` and the claim cannot promote

#### Scenario: Round-trip identity
- **WHEN** reverse and forward both execute and the composed round trip is byte-identical on every captured pair
- **THEN** the bidirectional requirement is satisfied

### Requirement: Verification records declare their claim kind
Every verification record MUST declare `claim_kind` from the mapping table's `claim_kinds` section; the declared kind selects the matrix row. A record with a missing or unknown `claim_kind` MUST be `UNVERIFIED-WITH-GAP`.

#### Scenario: Missing claim kind
- **WHEN** a verification record carries no `claim_kind` declaration
- **THEN** the verdict is `UNVERIFIED-WITH-GAP`

#### Scenario: Unknown claim kind
- **WHEN** the declared `claim_kind` is not in the mapping table
- **THEN** the verdict is `UNVERIFIED-WITH-GAP`

#### Scenario: Declared kind selects the matrix row
- **WHEN** the record declares a known `claim_kind`
- **THEN** the required checks are that kind's matrix row and the record must satisfy all of them

### Requirement: Bypass claims require positive/negative control
An `input_bypass` claim MUST demonstrate that the bypass input is accepted AND that a control input is rejected through the same path; one-sided acceptance is not sufficient.

#### Scenario: Bypass without a control
- **WHEN** the record shows the bypass input accepted but no rejected control input
- **THEN** the verdict is `UNVERIFIED-WITH-GAP`

#### Scenario: Positive and negative controls
- **WHEN** both the bypass acceptance and the control rejection execute on captured inputs
- **THEN** the bypass claim is eligible for CONFIRMED

### Requirement: Non-reversible claims follow the claim-kind matrix
Detection and classification claims MUST pass one-byte perturbation stability plus replay equality on captured inputs. Claims of a deterministic non-reversible kind (`static_constant`, `numeric`, `string`, `structure`) MUST pass their matrix `check_type` (plus replay equality when captured pairs exist). `negative_result` and `capability` MUST pass their matrix checks. A claim whose kind has no matrix row MUST be `UNVERIFIED-WITH-GAP`.

#### Scenario: Detection claim without perturbation check
- **WHEN** a detection or classification claim is recorded without perturbation stability and replay equality
- **THEN** the verdict is `UNVERIFIED-WITH-GAP`

#### Scenario: Deterministic kind passes its byte check
- **WHEN** a `static_constant` or `numeric` claim carries its matrix check plus TDD evidence (and replay equality when captured pairs exist)
- **THEN** the claim is eligible for CONFIRMED without a round trip

#### Scenario: Unknown claim kind
- **WHEN** the claim's kind has no matrix row
- **THEN** the verdict is `UNVERIFIED-WITH-GAP`

### Requirement: Unbacked REFUTED cannot block promotion
A REFUTED verdict MUST carry executed falsifier evidence (RED→GREEN plus a machine check). A REFUTED record without that evidence MUST degrade to `UNVERIFIED-WITH-GAP` and MUST NOT block PROVEN.

#### Scenario: REFUTED without executed evidence
- **WHEN** the latest red-team record says REFUTED but carries no executed falsifier or machine check
- **THEN** the verdict degrades to `UNVERIFIED-WITH-GAP` and does not block PROVEN

#### Scenario: REFUTED with executed evidence
- **WHEN** the REFUTED record carries a RED→GREEN falsifier and a passing machine check
- **THEN** the REFUTED verdict stands and blocks PROVEN

### Requirement: Findings are evidence-bearing, never noise
Every reported DIFF or finding MUST name a falsifier or evidence and MUST affect a load-bearing claim. Items that do not meet this bar MUST be suppressed to telemetry and MUST NOT appear as findings.

#### Scenario: Non-material item
- **WHEN** a checker observation cites no falsifier and does not affect a load-bearing claim
- **THEN** it is recorded as suppressed telemetry and is not a finding

#### Scenario: Evidence-bearing DIFF
- **WHEN** a finding cites the evidence, the failing comparison, and the affected claim
- **THEN** it is reported as a DIFF

### Requirement: Round-trip requires at least one captured pair
A bidirectional check MUST operate on at least one captured input/output pair established independently of the maker's artifact. A record with zero captured pairs or zero matched pairs MUST be `UNVERIFIED-WITH-GAP`.

#### Scenario: Zero captured pairs
- **WHEN** the round-trip record lists no captured pairs, or zero matched pairs
- **THEN** the verdict is `UNVERIFIED-WITH-GAP`

### Requirement: Perturbation stability is defined and bounded
Detection and classification claims MUST perturb the captured input by one byte at N sampled offsets and MUST report the classification stability rate; the claim passes only when the rate meets the policy constant and replay equality holds on the unperturbed pairs.

#### Scenario: Stability below the threshold
- **WHEN** the perturbation stability rate is below the policy constant
- **THEN** the verdict is `UNVERIFIED-WITH-GAP`

### Requirement: Execution venue is bounded
Falsifiers that transform captured bytes offline are host-safe. Executing the target sample MUST use the VM channel; when no VM channel is available the claim MUST be `UNVERIFIED-WITH-GAP` and MUST NOT be run on the host.

#### Scenario: No VM channel
- **WHEN** the falsifier requires executing the sample and no VM channel is available
- **THEN** the verdict is `UNVERIFIED-WITH-GAP`

### Requirement: The L2 REFUTED path uses the same evidence bar
The L2 verification path MUST apply the REFUTED evidence bar: an unbacked REFUTED MUST be reported as an evidence gap, not as a rejection of the claim.

#### Scenario: L2 REFUTED without evidence
- **WHEN** the L2 verifier returns REFUTED without executed falsifier evidence
- **THEN** the result is an evidence gap, not a REJECTED claim

### Requirement: Calibration is a settlement precondition
Settlement MUST run the per-verifier calibration check. A verifier that is 100% one-sided over the policy sample MUST block settlement of the claims it verified, even when the overall corpus is mixed. A calibration scan error MUST block settlement and be recorded (fail-closed at this precondition).

#### Scenario: One verifier in a mixed corpus is one-sided
- **WHEN** a corpus contains a verifier that is 100% one-sided over at least the policy sample
- **THEN** the claims that verifier verified do not settle

#### Scenario: Calibration scan fails
- **WHEN** the calibration scan cannot complete
- **THEN** settlement is blocked and the error is recorded

### Requirement: Machine-check entries are replay-sampled at settlement
Settlement MUST re-execute a policy-sampled subset of machine-check entries. A sampled entry that does not reproduce MUST fail the affected credit.

#### Scenario: Sampled entry fails to reproduce
- **WHEN** a sampled machine-check command does not reproduce its recorded actual
- **THEN** the affected credit fails and the mismatch is recorded

### Requirement: Oracle-backed refutation is oracle-bound
`oracle_backed_refutation` MUST be derived from a recorded oracle result, never from the artifact's status word.

#### Scenario: Refutation without an oracle result
- **WHEN** a REFUTED or NEGATIVE artifact carries no recorded oracle result
- **THEN** it earns no refutation trace credit
