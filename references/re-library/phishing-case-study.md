# Phishing Case Study: F040 routing-claim contamination

A documented incident where a same-topic PROVEN pair disagreed (F035 vs
F040) and the contaminated conclusion propagated into the fact base.

## Incident

F035 and F040 were both PROVEN, shared the same routing topic, drew
opposite conclusions, and had no supersedes link. The fact base froze the
wrong routing conclusion (the root cause of the fact_contradiction_gate
#47 incident).

## Lessons

1. When multiple PROVEN fact conclusions under the same topic-key set
   (claim_id / sample_refs / cites intersection) disagree, an explicit
   supersedes / superseded_by is mandatory; otherwise the overall PROVEN
   conclusion is untrustworthy.
2. A global contradiction scan (`fact_contradiction_gate.py <ws>`) must be
   run before completion; the local check of a single promotion cannot
   discover contradiction pairs that span claims.

## Related

- Detector: `scripts/fact_contradiction_gate.py`
- Completion transaction: `scripts/completion_gate.py` (global recomputation)
