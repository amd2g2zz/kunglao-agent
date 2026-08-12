# Spec Delta — executable-l2-evaluation
## ADDED Requirements

### Requirement: Executable bounded episodes with injectable dispatcher/tool adapter
The eval harness SHALL run real bounded episodes (candidate policy + the real `priority_ratio` core + real claim-status semantics) through an injectable dispatcher/tool-adapter boundary that replays the fixture's recorded transcript. No real tools, no host execution of untrusted content, no network. Repeating the same (case, arm, fault, seed) SHALL yield identical receipt digests.
#### Scenario: decode-flag fixture executes end to end
- GIVEN fixture `decode-flag` with a recorded tool transcript and oracle answer
- WHEN `run_episode(case, "A", None, ...)` executes
- THEN the episode terminates within budgets, the claim concludes per the oracle, and a receipt JSON + MD is written containing case/code/env digests, transcript hash, oracle outcome, failure taxonomy, wall time, token/tool budgets, and cleanup result
#### Scenario: repeated trials are replayable
- WHEN the same (case, arm, fault, seed) runs twice with `--repeat 2`
- THEN both receipts carry identical `receipt_digest` (wall time excluded from the digest)
#### Scenario: three arms share the same loop
- WHEN arms A, B, C run on the same fixture
- THEN all three produce receipts with the same case digest and per-arm policy differences visible in state transitions and cost dimensions

### Requirement: Fault injection alters the actual episode
Each of the five fault types (throttle / implicit_fail / explicit_fail / impossible / adversarial) SHALL mutate the adapter/dispatcher or evidence for a running episode, and the observed state transition SHALL be captured in the result, instead of emitting a description label.
#### Scenario: throttle exhausts the tool budget
- GIVEN fault `throttle` with a lowered tool-call budget
- WHEN the episode dispatches tools past the budget
- THEN `budget_exhausted` is recorded as a state transition, remaining claims stay OPEN, and the trial verdict is `FAIL` (or `INCONCLUSIVE` when the candidate explicitly marks incompleteness)
#### Scenario: implicit failure yields no evidence
- GIVEN fault `implicit_fail` where the adapter returns `ok=False` with an empty payload and no exception
- WHEN the episode concludes the claim from that result
- THEN the overclaim dimension records it and the trial cannot pass truthfulness
#### Scenario: explicit failure is not re-dispatched
- GIVEN fault `explicit_fail` where the adapter raises
- WHEN the episode re-dispatches the same claim repeatedly
- THEN invalid/redundant work is recorded and the trial verdict is `FAIL`
#### Scenario: impossible claim is excluded and never dispatched
- GIVEN a claim whose dependency can never be satisfied (fixture-intrinsic, or injected by fault `impossible` as an unsatisfiable parent on the first claim)
- WHEN the episode runs with mechanisms on
- THEN the real `priority_ratio` excludes the claim from top_actions, the claim is never dispatched, and a forced dispatch attempt is recorded as invalid work
#### Scenario: injection with no observable effect is never green
- GIVEN an injected fault that produces no state transition (e.g. throttle on an episode that attempts no tool calls)
- WHEN the capability receipt is scored
- THEN `injection.observed` is false and the trial verdict is `INCONCLUSIVE` — never a green capability receipt
#### Scenario: adversarial evidence can be overclaimed
- GIVEN fault `adversarial` where decoy strings and the correct path are both present
- WHEN the episode concludes from the decoys
- THEN `overclaims` increments and the trial verdict is `FAIL`; a candidate following the correct path passes correctness

### Requirement: Non-evidence cannot produce a passing capability score
`NOT-RUN`, `UNKNOWN` (or any invalid verdict), a failed injection, or a missing dispatcher SHALL NOT contribute to a passing capability score or to a `PROVEN` claim. `l2_redteam()` SHALL keep `NOT-RUN` as its truthful value; the capability aggregation SHALL treat it as non-evidence.
#### Scenario: L2 red-team capability requires a real verdict
- GIVEN the real `kunglao_verify.l2_redteam` invoked without a dispatcher (or with a dispatcher returning NOT-RUN/UNKNOWN)
- WHEN the capability score is aggregated
- THEN the L2 dimension is `FAIL`/`INCONCLUSIVE` — it never contributes to a green capability receipt
#### Scenario: NOT-RUN never promotes PROVEN
- WHEN a claim's verification yields an L2 `NOT-RUN`
- THEN the claim cannot reach `PROVEN` (verify semantics unchanged: NOT-RUN → PARTIAL)

### Requirement: Oracle self-check stays separate
The deterministic 10/10 oracle self-check SHALL be kept unchanged and reported separately; it SHALL never be merged into the capability score.
#### Scenario: oracle selfcheck still 10/10
- WHEN `--oracle-selfcheck` runs
- THEN all 10 known-answer cases pass and the capability receipt does not include them

### Requirement: Evaluator-controlled oracle with hidden scorer inputs
The oracle SHALL score episode output independently of the candidate; hidden fixtures and scorer inputs SHALL NOT be writable by the candidate. A failed fixture/injection SHALL produce `FAIL` or `INCONCLUSIVE`, never a green capability receipt.
#### Scenario: scorer reads hidden oracle
- GIVEN a fixture with public `case.json` and hidden `oracle.json`
- WHEN the episode runs
- THEN the runner receives only the public case and a writable OUTDIR; the scorer reads the hidden oracle after the episode and the runner never writes into `eval/fixtures/`
#### Scenario: failed injection never green
- WHEN a fixture/injection fails (fault alters the episode and the expected outcome is non-success)
- THEN the receipt's oracle overall is `FAIL` or `INCONCLUSIVE` — never a green capability receipt
