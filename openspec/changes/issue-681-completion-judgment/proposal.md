# issue-681-completion-judgment — completion = the independent checker

## Why

Issue #681 (e2e audit 2026-10-11, dev `8dd2a54f`): the pipeline's own
completion verdict points the opposite way from the unit's mechanical
checker. Of the 12 runs that left a candidate at the unit's contract
path, re-scoring with each unit's own `checker.py` (the same call the
ORACLE step makes) gives 4 PASS — and all 4 checker-PASSING deliveries
were reported BLOCKED or PARTIAL by the pipeline. Only 1 of 93 runs
ever reached the ORACLE stage. This is the reward function's body: if
completion cannot recognize a pass, no downstream credit assignment
can be trusted.

Three root causes:

1. **The stage sequence starves the judgment** — the C1..C7 → ORACLE
   loop breaks on the first FAIL/BLOCKED, so the ORACLE never judges
   the best-so-far candidate on exactly the runs that need it;
2. **The candidate resolver hardcodes a .py path** — `resolve_candidate`
   falls back to `artifacts/derive_reimpl.py` when task.yaml declares
   no `checker.candidate`; only 6 of 56 units declared one (all
   `client.py`), so .go/.js/.json/.txt families resolved a path whose
   suffix their own checker refuses (`eval_checker._validate_candidate`)
   — a silent .py fallback;
3. **finalize trusts the pipeline's self-assessment** — the final label
   is the stage loop's `final_status`, never the unit checker's verdict
   on what was actually delivered.

## What Changes

1. **The checker is the completion oracle (D-681.1)** — `finalize` runs
   the ORACLE on the best-so-far candidate whenever the run stopped
   short on a delivery-starved label (BLOCKED/PARTIAL) and a candidate
   exists at the unit's contract path. An ORACLE PASS upgrades the
   final label to the distinct `checker-PASS` (+ exit 0); anything
   else keeps the pipeline's own label. A checkpoint FAIL stays FAIL
   by design. The blocked stage remains visible in the checkpoint
   table — `checker-PASS` is a distinct label, not a laundering.
2. **Monotone delivery** — `runs/deliverable-best-so-far.json` is
   written on every finalize while a candidate exists (ws-relative
   path + sha256 + label); never deleted when a later resume finds
   nothing. A run never reports failure on passing work without also
   handing the work over.
3. **The candidate resolution contract (D-681.2)** — a unit that
   neither declares `checker.candidate` nor matches its family's
   contract suffix (`eval_contract.candidate_suffix`, the same face
   the checker grades against) at the default path emits exactly one
   typed `candidate-undeclared` event (ORACLE evidence detail + one
   `warn`) instead of silently resolving a .py path. All 34 tracked
   non-.py units now declare their contract path (`client{suffix}`,
   `verdict.json` for misdirection verdict documents, `answer.txt`
   for toolflex), each suffix-pinned to `eval_contract` by test; the
   key itself becomes a first-class schema citizen
   (`schemas/eval-task-v1.json` optional string +
   `eval_dataset._validate_candidate_decl` — a non-string declaration
   is a validation error, never a silent fall-through).

## Out of scope

- The py-derive-shaped `build_goal_op_doc` deliverable text (the C6
  goal-op template still names `artifacts/derive_reimpl.py` verbatim
  for every unit) — a prompt-shape card, not a labeling card.
- Migrating the e2e contract paths to the loop-runner's
  `runs/deliverables/candidate{suffix}` convention — the combat
  units' ws-root `client.py` contract is matrix4b G3's ruling and the
  6 existing declarations pin it.
- Re-verifying candidates at promotion time (C6) rather than at the
  finalize ruling — the ORACLE evidence file is the single judgment.
