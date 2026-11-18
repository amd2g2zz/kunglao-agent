## Why

Recorded behavior probability does not match the executed family-selection law. SNIPS also associates retained weights with the wrong rewards when a preceding row has zero target weight.

## What Changes

Define a single-decision action and its probability information set, reject unknown or untrustworthy probability records, and keep each SNIPS importance weight paired with the reward of its own decision. This change is in preparation; only the arithmetic is currently being implemented.

## Capabilities

### New Capabilities
- `behavior-propensity`: behavior probability provenance and valid off-policy evaluation.

### Modified Capabilities
None.

## Impact

The e2e family receipt and policy comparison code. This change does not alter production sampling or the base model. INV-001 and INV-003 are relevant to the dispatch and keyed learning signals; neither proves the OPE probability semantics.
