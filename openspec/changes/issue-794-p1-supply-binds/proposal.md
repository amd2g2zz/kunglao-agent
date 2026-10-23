# issue-794-p1-supply-binds — claim birth carries a hypothesis; the sampler binds; admission has teeth

## Why

The exploration layer is built and wired but never fed (production:
51job 8 claims / ctf-1 10 claims -> zero H-* files), and the sampler
never bound: the logs panel measured 17/17 sample_deviation rows joined
to dispatches that ran the DECLARED family, never the SAMPLED one (6/16
with propensity 0.0 — a probability-0 draw, invalid for IPS). The gate
read the layer only as an advisory; a hypothesis-less claim dispatched
freely. Feeding the existing machine — not a new subsystem.

## What Changes

1. **Claim birth = hypothesis birth (supply).** `ensure_claim_stub` in
   scripts/hypothesis_bridge.py: an idempotent, claim-linked OPEN
   hypothesis (the claim's stated mechanism as H1 candidate; pq-bound
   when the claim answers a primary question). Wired into BOTH code
   level mint paths — the split fan-out (mint_split_claims) and the
   obstacle promotion (failure_analysis_gate) — BEFORE the register
   write, so a failed stub refuses the mint cleanly. Arm mints already
   bind via the family hypothesis. A new `--ensure-stub` CLI is the
   admission guidance's one-command fix.
2. **Sampled-binds (R2).** The dispatch face treats the sampler's draw
   as the dispatch contract: a deviation is an EXPLICIT RECORDED
   decision with a COHERENT propensity — silent deviation REJECTs with
   the sampled family as the exit; reasoned deviation with
   propensity <= 0 REJECTs (never in the policy's support); reasoned +
   propensity > 0 passes with the reason and propensity riding the
   usage row and the sample_deviation event. The off-registry
   other(...) escape keeps its quarantine face. Narrows (never
   deletes) the recorded-decision amendment: the record rides the pass.
3. **Admission with teeth (eligibility face).** hooks/dispatch_gate.py
   `_supply_admission`: a register-recognized claim with a scaffolded
   hypotheses/ carrier and NO linked OPEN hypothesis holding a real
   candidate REJECTs (exit 2, HARD evidence class — a charter face)
   with guidance naming the fix. Linkage = the claim_id map face, or
   the register's hypothesis_ref to an OPEN family (the arm shape). 
   Fail-open retained ONLY for an unreadable carrier
   (hypothesis_supply_fail_open, the outage tiering). Asleep for
   pre-carrier workspaces and verifier-remediation dispatches (the D2
   honest trust path).

## Out of scope (deliberate)

- init seeding of structural-claim stubs — rides the init-v2 card
  (#791 lane; the no-analysis seeding contract there must be honored).
- The ranker core and its propensity pin (#792) — this card's bind
  check CONSUMES the sampler view; it does not touch the sampler.
- Settlement/pricing of hypothesis elimination — the pricing card.

## Impact

- hooks/dispatch_gate.py, hooks/worker_budget_sinks.py (faces)
- scripts/{hypothesis_bridge,claim_granularity,failure_analysis_gate,
  event_taxonomy}.py (supply + vocabulary)
- tests: 3 new files; the two faces' superseded pins updated in place
