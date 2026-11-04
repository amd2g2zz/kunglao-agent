---
name: llm-redteam-rubric
description: Scoring rubric for the kunglao-redteam adversarial checker — the written standard the red-team LLM applies when typing each claim/question CONFIRMED, REFUTED, or UNVERIFIED-WITH-GAP, in both claim-layer and verdict-layer modes. Anchors on the CREDIT_BY_CLASS ladder pattern (cross_validated 1.0 / unverified 0.3 / refuted 0.0 mapped to CONFIRMED / UNVERIFIED-WITH-GAP / REFUTED), the self-consistency majority-vote rule, blind-check discipline, edge cases, hard disqualifiers, and the escalate-vs-decide line. Read when writing or auditing a RED-TEAM VERDICT, when judging whether a pass was earned or collapsed, or when calibrating what a divergence must be reported as.
---

# LLM red-team rubric — kunglao-redteam

## Surface

The **kunglao-redteam** subagent is the LLM-judged surface: it attacks a
maker claim (claim layer) or re-derives the PQ coverage + attribution
(verdict layer) and types each item with a RED-TEAM VERDICT. The
adversarial isolation between maker and checker is DESIGN — this rubric
governs the checker's judgment layer only; the orchestrator owns the
maker-vs-checker comparison, and the mechanical gates (read barrier,
machine-check fence, adversarial summary signatures) are not the LLM's
to relax.

## Canonical vocabulary (no parallel scales)

- The verdict vocabulary is exactly **CONFIRMED / REFUTED /
  UNVERIFIED-WITH-GAP** per claim/question, plus **DIFF** for every
  divergence from the maker's conclusion, plus the **SELF-CONSISTENCY:
  PASS/FAIL** line. Nothing else is a verdict.
- The anchor pattern is the CREDIT_BY_CLASS ladder
  (`scripts/rlvr/step_credit.py`: cross_validated 1.0 / unverified 0.3 /
  refuted 0.0) — CONFIRMED sits at the 1.0 anchor, UNVERIFIED-WITH-GAP
  at the 0.3 anchor, REFUTED at the 0.0 anchor.
- Machine checks keep the repo's machine_check contract shape
  (`command` / `expected` / `actual` / `passed`); a check's boolean is
  evidence, not the verdict itself.
- Admiralty/ACH/Diamond are re-derivation METHODS in verdict-layer mode;
  they never mint a confidence number outside the vocabulary above.

## Scoring anchors

| Score | Verdict | What it looks like |
|---|---|---|
| 1.0 | CONFIRMED | Your independent derivation (>=2 DIFFERENT methods, majority agree) reproduces the claim's load-bearing value from raw evidence, every machine check passed=true, and the anti-collapse duty is met (>=2 counter-example directions searched and named). |
| 0.3 | UNVERIFIED-WITH-GAP | Real attack work happened but the evidence cannot settle the claim: a required channel was unavailable, the capture straddles an unresolvable ambiguity, or a method path could not complete. The gap is named with what evidence would close it. Honest verdict, not a failure. |
| 0.0 | REFUTED | Your derivation contradicts the claim (alternative explanation explains the bytes better, extrapolation beyond evidence, self-inconsistent numbers), or any machine check recorded passed=false — one red check alone forbids CONFIRMED and forces REFUTED or UNVERIFIED-WITH-GAP. |

A CONFIRMED reached through ONE derivation method has not been
self-consistency-checked — it is not a 1.0; it is UNVERIFIED-WITH-GAP
until a second independent path corroborates or exposes the hole.

## Edge cases

- **Paths split**: >=2 support and >=2 refute, or a path cannot
  complete => the claim is not self-consistent => UNVERIFIED-WITH-GAP
  and the divergence is itself a DIFF.
- **Replay-window contamination**: a recompute passing window-A pairs
  and failing window-B pairs is the signature of a rotated secret, not a
  wrong algorithm — segment the capture before typing the verdict.
- **Sampled-input bias**: before CONFIRMING coverage, recompute across
  the boundary classes the maker's sample misses (empty, unicode,
  max-length, boundary numeric).
- **Environment gap**: a value derived under an emulated profile that
  was never tested against the real environment is UNVERIFIED-WITH-GAP,
  never a pass.
- **Zero matched pairs / silent-green oracle**: zero pairs is honest RED
  evidence (REFUTED or UNVERIFIED-WITH-GAP); a comparator that stays
  green under a one-byte perturbation is broken — enforce
  mutation-must-red.
- **Pure-CTI claims**: the machine-check exception path (`machine_check:
  none` + reason + claim_kind) applies ONLY to claims with no artifact
  bytes; it waives the check, never the verdict vocabulary.
- **Web lane**: the oracle is the captured pair set — offline replay
  recomputation, never a live re-request (drift/rate-limit creates
  false DIFFs).

## Hard disqualifiers (force REFUTED / invalidate the pass)

- Reading the target's fact file, `facts/_INDEX.md`, `notes/`, the
  worker's status/plan, `runs/verification-*`, or `evidence/verdict.json`
  breaks blindness — the whole pass is invalid no matter what it
  concluded. Barrier rejections are the design working; re-scope to
  evidence, never route around.
- A challenge without a grounded falsifier (runnable command or concrete
  artifact path + what it would disprove) is rejected — "please
  double-check" is not a challenge and never counts.
- CONFIRMED without the anti-collapse search (fewer than two
  counter-example directions searched, or merely replaying the worker's
  own path) is the GAN-collapse failure — it is not a pass.
- Never recording a failed check, or recording only the checks that
  passed: every check runs into the block, passed=false included.
- Editing facts, claim-register, or worker outputs — the checker never
  makes; it writes only its report under `runs/`.

## Escalate vs decide

Ambiguity in the EVIDENCE => decide with the vocabulary above; an honest
UNVERIFIED-WITH-GAP beats a guessed CONFIRMED every time. Ambiguity in
COST or AUTHORITY — an attack needing a T3/VM session, a broken
challenge-chain ledger, a forged or wrong-key adversarial summary =>
stop and escalate to the orchestrator (name it in GAPs; do not retry a
broken chain, do not spend the VM without the orchestrator's call).

## Delivery (progressive disclosure)

This card loads by scenario — the recall face at dispatch
(`references_recall.py` on the red-team / adversarial-verification
scenario) or the citation line at the end of the red-team contract's
verdict vocabulary. The rubric is read when typing verdicts, not
wholesale into every dispatch.

## Sources

- `agents/kunglao-redteam.md` — blind rules + self-consistency
  majority-vote (lines 64-112), challenge protocol + anti-collapse
  (lines 114-133), machine-check oracle contract (lines 175-250),
  web-lane shapes + attack angles (lines 252-300), output format +
  verdict vocabulary (lines 302-334), verdict-layer method (lines
  336-409).
- `scripts/rlvr/step_credit.py` — CREDIT_BY_CLASS anchors (lines
  82-88).
- `references/contracts/machine-check-contract.md` +
  `references/schemas/machine_check_map.yaml` — the machine-check
  record shape and claim-type -> check-type table.
- `references/attribution-methodology.md` — Admiralty/ACH/Diamond
  re-derivation method (verdict-layer mode).
