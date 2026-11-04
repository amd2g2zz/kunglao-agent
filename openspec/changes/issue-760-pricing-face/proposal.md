# issue-760-pricing-face — the unknown set becomes computable; information-gathering gets a price

## Why

The loop's belief (component b, landed) records what a claim SAW and
what the worker DECLARED unknown, but "what we do NOT know" is still not
a computable object, and an information-gathering action has no price:
a dead path was re-probed 9 times in production with nobody counting the
waste, and probes ride the consumption account as free. This change is
the pricing slice of issue 760 ONLY.

## What Changes

1. **The unknown set (data face).** `unknown_set(ws)` in
   scripts/rlvr/pricing.py: a workspace-level VIEW projecting which
   primary_questions are UNDECIDED (no terminal claim answers them,
   with each one's open-candidate count) and which obstacles are OPEN
   (the obstacle registry's active rows; retraction is its only
   resolution transition). Pure projection over EXISTING keys (the
   canonical PQ parse, the claim register, the obstacle registry) —
   no new ledger, no new state owner.
2. **The price (computable, replayable, deterministic).**
   `price_action(ws, kind, target_id)`: expected information gain
   (bits: log2 of the target's live rival count, floored at one) x the
   undecided value weight, decayed by the target's committed-dispatch
   repeat count joined from the issue-800 dispatch ledger. A DECIDED
   target prices exactly 0 (the repeat-probe pin); a high-info probe
   structurally outprices a low-info one. No ts, no RNG inside the
   computation; the identity ts is stamped at emit.
3. **The joins.** Emitted price rows land in the issue-721 TELEMETRY
   family under the probe-price/1 stamp (no new file); the issue-801
   cockpit consumption face carries a `pricing` block
   (`probe_consumption`: probes / zero_info_probes / repeat_probes /
   billed_price — probes are no longer free); the dispatch
   supply-admission face reads the claim's price as ONE advisory
   `probe_price` trace at the approval point (never a gate decision;
   outage degrades to `probe_price_fail_open`).

## Out of scope (deliberate — the pricing slice only)

- Observation ingestion (the o/b ingestion edge) — component b, landed.
- The action vocabulary (distill and friends) — the A face.
- Composite/sampled admission (the pi face).
- The four-arm ablation — hard-gated behind the Rollout audit's
  9-item checklist (issue 806 board ruling); does NOT start here.
- The ranker core (issue 792), settlement_scorer (issue 802), and any
  gate decision change — pricing is advisory telemetry only.

## Impact

- scripts/rlvr/pricing.py (NEW — the face), scripts/rlvr/__init__.py
  (export map), scripts/event_taxonomy.py (two words, sorted)
- hooks/cost_input_capture.py (cockpit face's pricing block),
  hooks/dispatch_gate.py (supply-admission's advisory read)
- tests/test_pricing_760.py (NEW — 16 pins, synthetic fixtures)
- deploy-manifest.yaml (regenerated LAST)
