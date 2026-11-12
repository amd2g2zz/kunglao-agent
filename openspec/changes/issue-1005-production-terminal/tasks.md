## 1. Baseline and contract

- [ ] Restore the locked environment, record the full baseline, validate this change and its scoped invariant coverage.
- [ ] Capture the production Stop RED and record the independent-checker and terminal-status gaps.

## 2. Settlement and recovery

- [ ] Wire only eligible terminal Stop events, preserve distinct success, verified failure, surrender and interruption outcomes, and retain maker/checker separation.
- [ ] Verify idempotence, concurrent Stop, I/O faults, corrupted seals, process interruption and durable recovery without losing prior evidence.
- [ ] Capture sanitized face spans with stable IDs, independent roles, a real consumer and separate ledger/span fault tests.
- [ ] Exercise dispatch through independent checker, settlement, credit, posterior and subsequent decisions, including rejection, orphan and environment-failure handling.

## 3. Paired development evaluation

- [ ] Implement the five synthetic environments and paired policies using only supported production connections; mark unavailable ablations.
- [ ] Replay normal, disturbed and ablation scenarios with small seeds, then the 200+200 seed evaluation; publish reproducible trace, metrics and limitations.
- [ ] Verify the proposed S5 view-only behavior; leave owner-dependent acceptance open.

## 4. Validation

- [ ] Run the requested focused suites, full pytest, OpenSpec validation, scoped coverage and applicable quality gates; record actual pass/failure and remaining unknowns.

## Implemented slice receipt

- [x] Capture production Stop baseline: 2 failed / 14 passed (success and independently verified failure produced no episode).
- [x] Connect the final eligible production Stop to existing mission and round-credit owners without modifying reward arithmetic.
- [x] Exercise success/failure, refused final gates, second-Stop release, ineligible identities, concurrent Stop, durable intent write failure and partial-write recovery.
- [x] Prove armed synthetic dispatch → SubagentStop park/ruling consumption → Stop → same-dispatch credit → non-uniform posterior → changed subsequent fixed-seed choices.
- [x] Add terminal-only span writer and operator reader, including independent span/ledger failure tests.
- [ ] Add production dispatch/worker/checker stage spans and crash-at-process-exit coverage.
- [ ] Implement `devkit/experiments/v016_within_task.py`, five environments and 200+200 paired evaluation.
- [ ] Validate real Claude session liveness and real sample outcomes (outside frozen-model synthetic verification).

## Independent review P1 follow-up

- [x] Reproduce all three original independent fault probes against the current worktree (3 failed before fixes).
- [x] Distinguish internally swallowed notes read/parse failures from no obligations, with durable retry and no episode/reward side effects.
- [x] Verify existing participating learning seals before invoking recovery and before certifying completion; preserve invalid rows and missing/corrupt keys.
- [x] Require committed-dispatch Q-cell credit after recovery; make the real Stop block a swallowed bank failure and recover on a later Stop.
- [x] Record original fault probes, added fault regressions, related regressions and final validation on the revised staged candidate.
- [ ] Obtain independent specification re-review of the three P1 fixes.
