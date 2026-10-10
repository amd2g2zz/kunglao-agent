---
name: phishing-case-study
description: Same-topic contradiction technique — when two promoted conclusions under the same topic keys
  disagree, an explicit supersedes link is mandatory and a global contradiction scan must run before
  completion. When a same-topic promoted pair disagrees.
domain: method
family: process
---
# Same-Topic Contradiction (phishing case study)

A same-topic contradiction is two promoted conclusions that share the same
topic keys (sample refs / cited-evidence intersection), draw opposite
conclusions, and carry no supersedes link between them. Left unlinked, the
fact base freezes whichever conclusion landed last — and the wrong one can
propagate into every downstream answer built on that topic.

## Worked example (from a prior phishing engagement)

Two promoted conclusions covered the same routing topic, drew opposite
conclusions, and had no supersedes link. The fact base froze the wrong
routing conclusion and it propagated. The full incident narrative lives in
the case book: [case-book.md](../../../orchestration/failure-modes/case-book.md)
(Case 6).

## The technique: detect and resolve

1. **Detect globally, not locally.** A single promotion's local check cannot
   see contradiction pairs that span claims. Run the global contradiction
   scan before declaring completion:

   ```bash
   python scripts/fact_contradiction_gate.py <ws>   # exit 0 clean / 1 conflict
   ```

2. **Link explicitly.** When the scan (or review) surfaces a same-topic pair
   that disagrees, one conclusion must explicitly supersede the other
   (supersedes / superseded_by). Without that link the overall conclusion
   under the shared topic keys is untrustworthy no matter how strong each
   side looks in isolation.

3. **Recompute, don't hand-patch.** Resolution goes through the completion
   transaction's global recomputation (`scripts/completion_gate.py`), never
   through editing one side of the pair by hand.

## Expectation table

| Same-topic pair state | Consequence |
|---|---|
| Conclusions agree | Nothing to do |
| Conclusions disagree, supersedes link present | Newer one stands; older is history, not truth |
| Conclusions disagree, no link | Gate fails completion — supersede or refute one side before delivery |

## Related

- Detector: `scripts/fact_contradiction_gate.py`
- Completion transaction: `scripts/completion_gate.py` (global recomputation)
