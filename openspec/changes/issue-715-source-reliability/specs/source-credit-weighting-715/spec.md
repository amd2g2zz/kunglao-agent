# source-credit-weighting-715 delta — issue-715-source-reliability

## ADDED Requirements

### Requirement: Step credit is discounted by the learned source reliability

The step-credit module SHALL expose the composition

    step_credit = item_credit(meta) × source_reliability_theta

as `weighted_step_credit(items)`: the mean over the window's items of
each item's credit multiplied by a Thompson draw from the learned
source-reliability Beta for the item's source class (drawn via
`rlvr.source_reliability`; one fold reused across the window, and the
store read only when a labeled item is present). The module's
`step_credit` entry SHALL route through the composition, so the
production settle path carries the learned discount. Evidence from a
low-reliability source SHALL therefore be discounted automatically,
and evidence from a confirmed source SHALL keep its credit. An
evidence item carrying no source labels SHALL be weighted 1.0 - the
learning applies "if available" - which preserves the pre-discount
score byte-identically for every unlabeled window, including the
verification-class anchor scale and the module's own credibility
modulation, which the learned face neither reads nor changes.

#### Scenario: a refuted-heavy source's credit is discounted

- **WHEN** one source accumulates repeated refutations and another
  accumulates confirmations, and a cross-validated evidence item from
  each is scored through `weighted_step_credit`
- **THEN** the low-reliability item's credit is a small fraction of the
  anchor while the confirmed source's stays near it, each equal to
  `item_credit(meta) × theta` under the module's scoring rounding

#### Scenario: unlabeled evidence rides the neutral weight

- **WHEN** a window of evidence items that carry no source labels is
  scored through `weighted_step_credit` (or `step_credit`)
- **THEN** the score equals the module's pre-discount score exactly and
  no store read is required

#### Scenario: the production entry carries the discount

- **WHEN** `step_credit(items)` is called over a window containing
  evidence from a heavily refuted labeled source
- **THEN** the result equals `weighted_step_credit(items)` and falls
  below the item's undiscounted anchor
