# source-credit-weighting-715 delta — issue-715-source-reliability

## ADDED Requirements

### Requirement: Step credit is discounted by the learned source reliability

The credit face SHALL compose step credit with the learned source
reliability as

    step_credit *= source_reliability_theta

where theta is the Thompson draw for the evidence item's source class
(`reliability_weight`) and the multiplication clamps both factors into
[0, 1] (`apply_source_reliability`). Evidence from a low-reliability
source SHALL therefore be discounted automatically, and evidence from a
confirmed source SHALL keep its credit. An evidence item carrying no
source labels SHALL be weighted 1.0 - the learning applies "if
available", and label absence is never itself a trust signal.

#### Scenario: a refuted-heavy source's credit is discounted

- **WHEN** one source accumulates repeated refutations and another
  accumulates confirmations, and the same base credit is weighted for
  each
- **THEN** the low-reliability credit is a small fraction of the base
  while the confirmed source keeps most of it, and each result equals
  the base times its sampled theta

#### Scenario: unlabeled evidence rides the neutral weight

- **WHEN** `reliability_weight` is asked for an evidence item that
  carries no `source` label
- **THEN** the weight is exactly 1.0 and no store read is required
