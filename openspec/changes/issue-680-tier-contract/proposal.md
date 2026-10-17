# issue-680-tier-contract — the dispatch envelope's tier is derived, not chosen

## Why

Issue #680 (live C-007 deadlock): the dispatch envelope's `tier` is a free
LLM input (`lib_kunglao.parse_dispatch_json` accepts any of 1/2/3) with no
consistency check against `action_tier` — `min(evidence_tier_attempted+1,
3)`, the claim's own mechanical next tier (#103/#107). Meanwhile
`worker_budget.check_tier_gate` requires every open claim at
`evidence_tier_attempted >= tier-1` for a tier>=2 dispatch, and **no code
ever writes `evidence_tier_attempted`** (only init seeds it). The ladder
can therefore never climb: the LLM declares tier=2 for an eta=0 claim, the
gate rejects on eta=0, and nobody ever does the tier-1 work that would
raise eta — a self-deadlock that left the acceptance claim (C-007) with
zero artifacts. Two disconnects: the tier is free input instead of being
checked against `action_tier`, and `evidence_tier_attempted` has a reader
but no writer.

## What Changes

1. **Tier consistency gate** (`hooks/worker_budget_gates.py::
   check_tier_consistency`): a dispatch whose envelope `tier` differs from
   `action_tier(claim)` is REJECTED with the correct value in the
   guidance. A recorded deviation (`agent-reasoning:` prefix — same
   discipline as the #310 agenttype / #496 top-1 faces) passes with a
   stderr note. Verifier-remediation dispatches (a verifier-class agent
   for a PROVEN claim — the #237 D2 pass-through) skip the gate entirely:
   a redteam/verdict-scorer tier is not the claim's evidence-ladder
   step, and gating it would re-create the blocked-remediation deadlock
   class. Wired into the `pre_check` battery as `tiercons`, BEFORE the
   ladder gate (on the C-007 shape both reject; tiercons carries the
   actionable message). Uncheckable shapes allow (no claim id, claim not
   in register, priority_ratio import unavailable).
2. **eta writer** (`hooks/worker_budget_sinks.py::
   _write_eta_at_dispatch`): after an ALLOW, the dispatched claim's
   `evidence_tier_attempted` is raised to `max(current_eta, tier)` — the
   missing writer. Dispatch-time = ATTEMPTED semantics (design D-680.1).
   Monotonic; ws_yaml canonical renderer (single-writer); fail-open.
3. **rank_feeds `tiers` key** (`scripts/priority_ratio.py::
   _emit_rank_feeds`): additive `tiers` mapping (claim -> action_tier)
   so the decision face can see the tier the envelope must carry.
   Existing keys untouched.
4. **`Action.to_dict()` carries `tier`** (additive) so `--json` consumers
   see it; the #12 frozen capture updated (scores/order unchanged).

## Out of scope

- `check_tier_gate`'s breadth-first invariant (every open claim at
  eta >= tier-1) stays exactly as-is — only the tier SOURCE changes, per
  the issue's ruling.
- `tier_rules.tier_for_claim` (the #241 claim-feature rule — what tier a
  claim's WORK needs) is a different axis from `action_tier` (what tier
  the ATTEMPT HISTORY allows); it remains advisory (recall_inject).
- Settle-time eta writes (outcome-based climbing) — rejected in design.md.
