---
name: llm-settlement-rubric
description: Scoring rubric for the kunglao-settler blind settlement ruling — the written standard the settler LLM prices raw step artifacts against before the deterministic validator stack (citation wall, rail clamp, oracle lock, anti-surrender floor) settles the ledger row. Concrete credit anchors on the CREDIT_BY_CLASS ladder pattern (cross_validated 1.0 / unverified 0.3 / refuted 0.0), edge cases, hard disqualifiers, and the escalate-vs-decide line. Read when ruling per-step credits on a blind-settlement input doc, when auditing why a settlement row landed where it did, or when calibrating what partial credit means for a step artifact.
---

# LLM settlement rubric — kunglao-settler

## Surface

The **kunglao-settler** subagent is the LLM-judged surface: it prices raw
step artifacts into per-action credits and one `trajectory_credit`. Its
RULING is judgment; everything after it is mechanical —
`scripts/rlvr/settlement_scorer.py` re-checks the blind input, then
`rlvr.scalar.validate_verdict_doc` runs the deterministic stack (citation
wall -> rail clamp -> oracle lock + anti-surrender floor) and only a
valid verdict writes a ledger row. This rubric governs the ruling layer
ONLY; it never licenses re-implementing or second-guessing the stack.

## Canonical vocabulary (no parallel scales)

- Per-action `credit` and `trajectory_credit` are scalars in [0, 1]
  (`agents/kunglao-settler.md` output contract; clamp at
  `scripts/rlvr/scalar.py` `clamp_credit`).
- The named rails are the validator's OUTPUT_RAILS: GOLD [0.85, 1.0],
  SILVER [0.55, 0.85], BRONZE [0.15, 0.55], TRACE [0.0, 0.05]
  (canonical 0.01), NEUTRAL/RED 0.0 — declared reference bands, not
  tunable weights.
- The anchor pattern is the CREDIT_BY_CLASS ladder
  (`scripts/rlvr/step_credit.py`): cross_validated = 1.0, unverified =
  0.3, refuted = 0.0. The settler prices steps on the same shape.
- A settlement is never a model opinion in the reward-rules sense:
  signals the settler produces are shaped into the verdict doc, and the
  ledger row's authoritative reward comes from the validator, not from
  prose.

## Scoring anchors

| Score | Class | What it looks like |
|---|---|---|
| 1.0 | cross_validated | The artifact proves the step's load-bearing output AND the oracle face is green — a checker pass, byte-exact replay, or terminal PROVEN/VERIFIED/NEGATIVE finding the artifact directly carries. Full credit for that step, no discount. |
| 0.3 | unverified | Real step work visible in the artifact (a genuine attempt, a captured intermediate, a method run that produced evidence) but no green gate cross-validates it. Partial credit; the step advanced the trajectory without proving its output. |
| 0.0 | refuted / nothing | The artifact refutes the step's claim, the step surrendered without evidence, or there is no artifact at all. Also the floor the oracle lock settles to on a fail without replay evidence. |

Between anchors, place the credit by what the artifact proves, not by
effort: a step whose output is byte-verified sits at the GOLD rail; a
step with a credible but unchecked intermediate sits at the 0.3 anchor
or just above; anything resting on narrative rather than artifact bytes
stays unverified. An Admiralty reliability letter (A..F) may modulate a
source-sourced item multiplicatively in [0.5, 1.0] — reliability refines
the anchor, it never invents one.

## Edge cases

- **Green gate on a refuted proposition**: the refutation reproduced —
  the ORIGINAL claim's step still prices 0.0; only the refutation work
  itself is real step work.
- **Oracle pass**: locks trajectory reward at 1.0 regardless of the
  settler's trajectory_credit — never write a lower number and expect it
  to hold; write what the artifacts show, the lock is mechanical.
- **Oracle fail**: the trajectory credit caps at the TRACE rail top
  (0.05); with rerun-reproducible evidence it floors at the TRACE
  canonical 0.01 (refuted-with-replay-evidence is a low positive).
- **Sha drift**: an artifact whose bytes do not hash to the input doc's
  sha256 is NOT a 0.0 ruling — it is `status: blocked | artifacts: none
  | note: sha drift`. Ruling on bytes you never saw fabricates credit.
- **Determinism**: same input doc + same artifact bytes => same verdict
  bytes. No timestamps, no prose flavor, no sampled judgment inside the
  verdict doc.
- **Out-of-range credit**: the entry clamps range violations
  mechanically — but a ruling that needs clamping is a mispriced
  ruling; price inside [0, 1] the first time.

## Hard disqualifiers (force the bottom / nothing settles)

- ONE unresolvable evidence citation rejects the WHOLE verdict doc
  (fail-closed hallucination wall). Cite only artifacts your input doc
  names; never cite a guess.
- Missing or empty settler identity: credit without a named grader does
  not settle — nothing in the doc is valid.
- Any read past the blind barrier (notes/, facts/, worker-status,
  verification records, evidence/verdict.json, the policy learning
  faces) or a helper-subagent route around it: the ruling is invalid
  regardless of its numbers.
- Surrender without replay evidence settles 0.0 — an "it did not work"
  with no captured artifact is the anti-surrender floor's exact target.
- Do NOT emit `reward` / `band` / `rule_id` / `evidence_refs` in the
  verdict doc; a doc that carries them misrepresents who settles.

## Escalate vs decide

Ambiguity about WHAT an artifact is => decide from the artifact bytes
(the rubric above). Ambiguity about WHETHER you may rule — missing input
doc, sha drift, a denied face you cannot work around, a rules table that
will not hash => **blocked, never a guess**; the orchestrator
re-dispatches with corrected paths. Inventing a rule to cover a missing
capability is a disqualifier, not a decision.

## Delivery (progressive disclosure)

This card loads by scenario — `references_recall.py` on the settlement
scenario, or the settler dispatch contract's citation line — never
wholesale into every prompt. The settler contract carries the pointer;
the rubric is read when ruling, not at every round.

## Sources

- `agents/kunglao-settler.md` — blind contract (lines 38-68), output
  schema + credit rails (lines 77-102), hard constraints (lines
  104-115).
- `scripts/rlvr/settlement_scorer.py` — blind input builder + settlement
  gate (lines 166-261), excluded faces (lines 70-87), `settle_blind`
  order (lines 278-314).
- `scripts/rlvr/scalar.py` — OUTPUT_RAILS (lines 1210-1224),
  `clamp_credit` (1229-1237), `resolve_citations` (1254-1270),
  `oracle_lock` + anti-surrender floor (1273-1296),
  `validate_verdict_doc` (1299-1335).
- `scripts/rlvr/step_credit.py` — CREDIT_BY_CLASS anchors (lines
  82-88), classification order (lines 128-140), RELIABILITY_WEIGHT
  (lines 107-117).
