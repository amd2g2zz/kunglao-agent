## Context

The action is the method family actually executed on one dispatch. The candidate support is the set authorized and available at that decision. The information set must identify whether candidate draws are conditioned on and must match between behavior and target probabilities. A conditional draw weight is not the marginal probability of a trajectory or an externally declared action.

## Decisions

A state-derived deterministic seed, an unmatched estimate, an override, a historical record without known semantics, or ambiguous dispatch identity yields unknown probability and is excluded from OPE with an explicit count. A random control arm may expose a conditional-on-draw propensity only when its independent randomization, support, executed action and information set are demonstrated. ESS below 20 or below 0.2 of eligible rows yields insufficient overlap and no ranking. These are forthcoming tasks, not implemented by the arithmetic patch.

The experimental `ControlledOPE` design is constructed by a trusted caller outside the audit stream before actions, with fixed positive weights and ordered decision IDs. `compare(experiment=...)` replays its independent selection stream and matches source, fixed-weight information set, complete support, selected family and probability against the audit and transition before accepting a row. Default CLI/production calls pass no experiment; labels inside audit records alone cannot enable evaluation. Seed replay proves consistency only: external generation and preregistration of that seed, the pre-action decision set, and reward independence remain experimental assumptions, not verified facts. The real production path still does not bind its launch attempt identifier to both carriers; repeated claim/family rows are refused and counted. This explicit experiment interface requires further independent review and integration with the eventual production identity contract.

SNIPS keeps the weight and reward for the same accepted decision. Zero target weight or invalid probability must never shift the next decision's reward onto a different weight. Bootstrap resampling calls this same estimator. A record with a non-finite probability, target probability, weight or reward is not a valid contribution.

Candidate weights are scaled before calculating the Thompson ratio so a finite sum cannot overflow. Rewards are separately scaled before calculating the weighted mean. If a computed result is still non-finite, the estimate is unavailable rather than an infinite value or an invented zero.

If no bootstrap replicate produces an estimate, the interval is unavailable (`null`), not a fabricated zero interval. When bootstrap was requested and an estimated policy has no interval, `compare` reports underpowered and emits no ranking. Existing valid replicates retain the same percentile interval interface.

## Integration contract

`compare` calls `snips` for each target policy and `_bootstrap_ci` calls `snips` on resampled decisions. Input is a decision's executed family, candidate weights, behavior propensity and realized reward; output is a self-normalized estimate and effective sample size. The fixture fingerprint is the 0/1 two-row example where the first target weight is zero: the value must be 1, not 0. INV-001 and INV-003 are relevant live dispatch and credit signals, not proof of OPE correctness.

## Scope and verification

First isolate the arithmetic failure using the real estimator; then after the candidate-support PR lands rebase onto dev and complete actual receipt provenance, OPE exclusions, unique dispatch attribution, ESS and independent-randomization controls. No actual model execution or sample execution is involved. Direct baseline file hash was verified against the indexed commit; GitNexus upstream impact for `snips` is LOW: direct callers `compare` and `_bootstrap_ci`, four impacted symbols, no named execution processes.
