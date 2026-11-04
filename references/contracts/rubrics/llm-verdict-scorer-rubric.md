> **RETIRED (#886)**: superseded by the deterministic executor
> `scripts/verdict_scorer.py` (C0a/C0b gates over the canonical PQ
> parse). This rubric is retained as the historical judgment spec; the
> adversarial gate stays orchestrator-side at signing.

---
name: llm-verdict-scorer-rubric
description: Scoring rubric for the verdict-scorer PQ-coverage ruling — the written standard the scorer LLM applies when deciding answered/unresolved per primary question via the C0a/C0b confidence bands, answers_question matching, and PROVEN status. Anchors on the CREDIT_BY_CLASS ladder pattern (cross_validated 1.0 / unverified 0.3 / refuted 0.0 mapped to answered / partial-with-degradation / unresolved), edge cases including the reproduction controlled-comparison demand, hard disqualifiers, and the escalate-vs-decide line. Read when writing or auditing evidence/verdict.json, when judging whether a question was honestly answered, or when calibrating degraded[] and self_audit entries.
---

# LLM verdict-scorer rubric — PQ coverage + confidence bands

## Surface

The **verdict-scorer** subagent is the LLM-judged surface: for each
`task_spec.yaml` `primary_questions[]` entry it finds the answering fact
via `answers_question`, verifies PROVEN status + confidence_band, and
writes `evidence/verdict.json` (analysis_verdict schema v11). This
rubric documents TODAY'S judgment contract; any scripting-down of this
surface rides its own card (#886) — until that lands, the judgment is
the scorer's, bounded by the mechanical gates it consumes
(convergence_check semantics, fact_contradiction_gate output,
adversarial_gate BLOCKED states).

## Canonical vocabulary (no parallel scales)

- The confidence vocabulary is exactly **C0a / C0b** (mirroring
  convergence) over fact frontmatter: `status: PROVEN` +
  `confidence_band: PROVEN-FULL` (C0a); the `need: model_selection`
  terminal pattern (C0b). Verdict fields are `answered: true|false`,
  `gap`, `unresolved[]`, `contradictions[]`, `degraded[]`,
  `self_audit.evidence_strength: strong|mixed|weak`. Nothing else is a
  confidence scale.
- The anchor pattern is the CREDIT_BY_CLASS ladder
  (`scripts/rlvr/step_credit.py`: cross_validated 1.0 / unverified 0.3 /
  refuted 0.0) — an honestly answered question sits at the 1.0 anchor,
  a partially-covered or degraded-but-real coverage at the 0.3 anchor,
  an unanswered or falsely-answered question at the 0.0 anchor.
- "Verdict is never more lenient than convergence": if
  convergence_check.py would not declare CONVERGED for a question, the
  scorer MUST NOT mark it answered.

## Scoring anchors

| Score | Class | What it looks like |
|---|---|---|
| 1.0 | cross_validated (answered) | A claim whose `answers_question` matches the question links a fact with `status: PROVEN` AND `confidence_band: PROVEN-FULL` (C0a), or the C0b pattern holds (one linked fact terminal PROVEN, remaining candidates REFUTED/DEFERRED); no gate-reported contradiction touches it. `answered: true`, `gap: null`. |
| 0.3 | unverified (partial / degraded) | Real coverage exists but a named condition is short: PROVEN without PROVEN-FULL, C0b candidates left OPEN/PARTIAL (recorded, not accepted), or coverage complete but carried with `degraded[]` honesty entries (missing files, partial confidence). The question's state is "answered with recorded degradation", never silently accepted. |
| 0.0 | refuted / unresolved | No claim answers the question, the answering fact is not PROVEN, a reproduction question lacks its controlled comparison, or a contradiction forces `correct: false`. `answered: false` with the gap named, question in `unresolved[]`. |

## Edge cases

- **Reproduction questions** (`reproduction: true`): C0a/C0b alone can
  NEVER answer them — the PROVEN answering claim must additionally
  carry a controlled-comparison replay artifact
  (`evidence/replay-*.json` / `replay_evidence:`) with byte-matched
  pairs. "Ran without error / env-filling stopped erroring" is a
  means-state, not the end-state: record it in `degraded[].reason` when
  a worker offered it, and mark the question unresolved.
- **A PARTIAL fact never answers a question** — any confidence_band
  below PROVEN-FULL leaves the question in `unresolved[]` (C0b's
  terminal-PROVEN requirement is the only relaxation).
- **Adversarial gate BLOCKED**: open challenges / broken chain /
  unauthenticated summary mean you cannot sign PROVEN. Mechanical — no
  override. Broken chain and forgery are escalate, not retry.
- **Contradictions**: consume `fact_contradiction_gate.py` output
  read-only; two PROVEN same-topic facts without supersedes/CONFLICT
  resolution each land in `contradictions[]` and set `correct: false`.
  Never pick one silently, never re-implement the detection.
- **Role split**: verdict-scorer verifies TRUTH; redteam verifies
  VALUE. A claim passing you but redteam-blocked stays unsigned — that
  is the design working.

## Hard disqualifiers (force the 0.0 anchor)

- Marking a question answered when the answering fact lacks PROVEN
  status, or lacks PROVEN-FULL outside C0b.
- Accepting a reproduction question without matched pairs — "ran
  without error" as answer evidence is the canonical false-green.
- Inventing evidence or filling gaps with assumptions; any entry in
  `primary_questions[]` whose `cited_fact` does not resolve to a real
  fact file.
- Ignoring gate-reported contradictions, or editing any input
  (task_spec, claim-register, facts) — inputs are read-only.
- Silently dropping an unanswered question from `unresolved[]` — the
  fail-closed convention requires the gap on the record.

## Escalate vs decide

Ambiguity about WHICH fact answers => decide by the `answers_question`
field; when no claim claims the question, that IS the answer
(unresolved, gap: "no answering claim"). Ambiguity about WHETHER you can
rule — missing task_spec or claim-register, an unreadable fact base, an
adversarial-gate broken chain or forgery => **stop**: missing inputs are
`status: blocked` after a plan update; broken chain / forgery escalate
to the orchestrator. Never guess an answer to keep the pipeline moving.

## Delivery (progressive disclosure)

This card loads by scenario — the recall face at dispatch
(`references_recall.py` on the verdict / PQ-coverage scenario) or the
citation line at the end of the scorer's PQ-coverage contract. The
rubric is read when building the verdict, not wholesale into every
round.

## Sources

- `agents/verdict-scorer.md` — hard constraints + convergence mirror
  (lines 51-58), C0a/C0b definitions (lines 98-109), reproduction
  controlled-comparison rule (lines 111-126), verdict build +
  cross-consistency (lines 128-140), output schema v11 (lines 142-189),
  anti-patterns (lines 191-201).
- `scripts/rlvr/step_credit.py` — CREDIT_BY_CLASS anchors (lines
  82-88).
- `references/schemas/schema.md` — fact.status + confidence_band
  schema; `references/contracts/machine-check-contract.md` — the
  adversarial-gate record shape.
