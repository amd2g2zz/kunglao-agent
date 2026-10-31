---
name: llm-eval-grading-rubric
description: Scoring rubric for the eval harness's judgment faces — the written standard governing how an eval run's verdict vocabulary (PASS/FAIL/SKIP/REFUSED, completed/exhausted/session_error, dense layers_completed/N) is applied around the mechanical graders, including the pass@k accounting rules (fixed-k same-config attempts, exhausted counts into the FAIL denominator, SKIP only for harness fault), the gap-redo decision, and the misdirection verdict-face failure codes. Anchors on the CREDIT_BY_CLASS ladder pattern (cross_validated 1.0 / unverified 0.3 / refuted 0.0 mapped to PASS / dense-partial / FAIL). Read when classifying post-session rows, when deciding a gap-redo round, when reading checker output into a results row, or when auditing whether an eval verdict was honestly graded.
---

# LLM eval-grading rubric — pass@k harness judgment faces

## Surface

The eval harness's graders are MECHANICAL (`scripts/eval_checker.py`,
`scripts/eval_chain_grader.py` — byte/execution-level oracles). The
LLM-judged faces live AROUND them: the loop runner's post-session
classification (completed / exhausted / session_error), the gap-redo
decision, the arm/budget accounting that feeds `pass_at_k_contribution`,
and the verdict-class checker faces (misdirection/rotation) whose
failure codes an operator or auditing LLM reads. This rubric governs
those judgment calls; it never licenses overriding a mechanical VERDICT.

## Canonical vocabulary (no parallel scales)

- Checker verdicts are exactly **PASS | FAIL | SKIP | REFUSED**
  (exit 0/1/3/2 in eval_checker.py and eval_chain_grader.py; REFUSED
  means bad task/candidate, never a model failure).
- Loop rows are exactly **completed | exhausted | session_error**
  (`loop.status`), and tier runs additionally carry
  **harness_contaminated** (diagnostic only — the verdict is
  unaffected).
- Failure signals come ONLY from FAILURE_CODES (CONSTANT_MISS,
  PAIR_MISMATCH, TOOLCHAIN_MISSING, BAD_CANDIDATE, BAD_TASK,
  MISATTRIBUTED, WRONG_CORRECT_PATH, ROTATION_UNPROVEN, REHOOK_LOOP,
  EXHAUSTED) — no invented codes.
- The anchor pattern is the CREDIT_BY_CLASS ladder
  (`scripts/rlvr/step_credit.py`: cross_validated 1.0 / unverified 0.3 /
  refuted 0.0) — PASS at the 1.0 anchor, a dense partial or
  honest-measurement row at the 0.3 anchor, FAIL at the 0.0 anchor.
- pass@k accounting (owner ruling): a FIXED k of same-config attempts
  is the cap; a candidate is PASS or FAIL — **exhausted (budget/wall
  death) counts INTO the FAIL denominator**; **SKIP is reserved for
  harness fault** (toolchain absent, preflight failure) and never
  stands in for a model failure.

## Scoring anchors

| Score | Class | What it looks like |
|---|---|---|
| 1.0 | cross_validated (PASS) | Every armed oracle face is green mechanically: constants hit, pairs reproduce (published AND checker-minted probes), or the dense chain completes all layers (layers_completed == layers_total). |
| 0.3 | unverified (dense partial / honest measurement) | A real deliverable that completes SOME but not all graded layers (dense score = completed/N), or a non-PASS row that is still a measurement (exhausted arm with a harvested deliverable, FAIL with structured FAILURE codes). These rows feed the denominator — they are data, not garbage. |
| 0.0 | refuted (FAIL / refusal-shaped failure) | The checker is red on a delivered candidate (CONSTANT_MISS, PAIR_MISMATCH), the verdict face shows a judgment defect (MISATTRIBUTED, WRONG_CORRECT_PATH, ROTATION_UNPROVEN, REHOOK_LOOP, EXHAUSTED), or the attempt died with neither captures nor conclusion. |

## Edge cases

- **Budget/wall death is EXHAUSTED, never a crash**: both kill faces
  (runner wall-cap SIGKILL, CLI `--max-budget-usd` stop) land the same
  TERMINAL exhausted row; whatever the loop wrote before the kill is
  still harvested and graded. Known documented mislabel: a genuine
  crash whose partial spend reads at/over the cap classifies exhausted
  (both flavors remain non-PASS measurement rows; the verdict is
  unaffected).
- **TOOLCHAIN_MISSING is SKIP, never FAIL** — a missing go/node
  toolchain degrades to a structured SKIP with rc=3; a run with no hard
  failures is SKIP, not a false red.
- **REFUSED (BAD_TASK / BAD_CANDIDATE)** is a harness-side rejection —
  it never counts as a model FAIL and never as a pass.
- **harness_contaminated**: workspace-escape drift is marked on the
  session row and diagnosed, but the verdict already ran and stands.
- **Gap-redo**: allowed ONLY when a candidate was DELIVERED and FAILED
  the mechanical checker with wall+budget remaining — never on
  SKIP/REFUSED (there is no gap to close). ONE redo max; the prompt
  carries GAP-shape only (which faces failed, by how much), never the
  checker's derived answer; the redo's verdict replaces the original,
  checker-strict.
- **Memorization traps are zero by construction**: constant-hit requires
  the variant's MUTATED constants; replay-roundtrip mints fresh probes
  from the variant seed — copying published pairs or canonical family
  constants scores zero. That is the checker working, not a judgment
  call.
- **Arm FAIL/exhausted rows are measurements** — a run containing them
  completed; they are never loop crashes and never suppress the row.

## Hard disqualifiers (force the 0.0 anchor / invalidate the row)

- Recording PASS from anything but the mechanical oracle faces — a
  session's self-report, a narrative claim, or an unrun check is never
  a pass (the checker verdict is the hard currency).
- A verdict-face claim without probe evidence (bare environment
  verdict) is MISATTRIBUTED by construction — it can never grade as
  correct.
- Inventing a verdict value or failure code outside the vocabularies
  above; silently reclassifying a FAIL as SKIP (SKIP is harness fault
  only).
- Feeding the checker's derived answer into a redo prompt — GAP-shape
  only; leaking the expected value launders the grade.
- Counting a SKIP or REFUSED row into the pass@k denominator — only
  FAIL and exhausted belong there.

## Escalate vs decide

Ambiguity between two measurement flavors (exhausted vs session_error
at the cap boundary) => apply the documented heuristic and record it —
the row's verdict is unaffected either way. Ambiguity about whether the
HARNESS itself is broken (preflight failures, drift on the graded
surface, an oracle that stays green under perturbation) => stop and
escalate with the structured evidence (harness-events row, failure
codes); never patch the task unit or the checker mid-run to make a row
green.

## Delivery (progressive disclosure)

This card loads by scenario — `references_recall.py` on the
eval-grading scenario, or the citation line in the harness checker's
contract header. The rubric is read when classifying results or
deciding redos, not wholesale into every session prompt.

## Sources

- `scripts/eval_checker.py` — checker contract: METRIC/FAILURE/
  EVIDENCE/VERDICT lines, exit contract 0/1/2/3, oracle faces
  (lines 1-53).
- `scripts/eval_chain_grader.py` — dense per-layer grading, layer =
  all-ops-pass, skip face (lines 1-38).
- `scripts/eval_dataset.py` — CHECKER_KINDS, REQUIRED_METRICS incl.
  pass_at_k_contribution (lines 111-118), FAILURE_CODES (lines
  115-127), results_row shape (lines 409-427).
- `scripts/eval_loop_runner.py` — budget/wall terminal exhaustion +
  harvest-before-grade (lines 45-56), workspace-escape gate +
  harness_contaminated (lines 58-66), gap-redo M2 (lines 68-76),
  gap_redo_decision (lines 1309-1325), budget-cap heuristic +
  mislabel caveat (lines 1581-1605), _session_status (lines
  1596-1607), preflight SKIP (lines 1610-1631).
- `scripts/rlvr/step_credit.py` — CREDIT_BY_CLASS anchors (lines
  82-88).
