# design — issue-681-completion-judgment

## D-681.1 — the checker is the completion oracle

Completion is not the pipeline's self-assessment; it is the unit's
independent `checker.py` PASSing the candidate that was actually
delivered. The ruling lives in `finalize` (`_checker_completion_ruling`):

- **Scope: the delivery-starved labels — BLOCKED and PARTIAL.** These
  are exactly the labels the audit measured on checker-PASSING work:
  the stage loop's early break starves the ORACLE on the runs that
  need the judgment most. When one of them is the run's label AND a
  candidate exists at the unit's contract path, the ORACLE step runs
  NOW (it appends its result to the checkpoint table; evidence + audit
  row land through the canonical `_record` seam).
- **An ORACLE PASS upgrades the label to the distinct `checker-PASS`
  and exit 0.** The label is distinct from `ALL-PASS` on purpose: the
  blocked stage stays visible in the checkpoint table (nothing is
  laundered), while downstream consumers (the reward function, the
  operator dashboard) see completion for what it is — the checker's
  call. An ORACLE non-PASS keeps the pipeline's own label and code
  untouched.
- **A checkpoint FAIL stays FAIL.** A hard FAIL (gate violation,
  contaminated staging, raising step) is a real defect; upgrading it
  on a checker PASS would launder the defect behind a green label.
  The candidate still reaches the operator through the delivery file
  (below) — the label stays honest, the work is not withheld.
- **Fail-open, one warn.** A raising checker at finalize (unreachable
  repo, broken `uv`, scripted-runner gaps in tests) warns once
  (`e2e.checker_completion_ruling`) and keeps the original label —
  the report is the harness's product and must never be lost.
- **`_final_verdict_of` is unchanged.** It reads the ORACLE evidence
  file, which the finalize-time run has already written — the report's
  `oracle` block carries the ruling's verdict either way.
- **Monotone delivery (`_deliver_best_so_far`).** On every finalize
  while a candidate exists, `runs/deliverable-best-so-far.json` is
  written: schema, run/unit/family, the final label, the ws-relative
  candidate path, its sha256, and the recorded ts. It is never deleted
  when a later resume finds no candidate — a delivered artifact is not
  retracted (monotone hand-off). No candidate means no file: honest
  absence, never a fabricated pointer.

### Rejected alternatives

- **"Just fix the path"** (teach `resolve_candidate` the family
  suffix and stop there): rejected — the labeling disagreement is the
  defect; a path fix alone leaves completion trusting the stage loop's
  `final_status`, and the measured 100% disagreement on passing
  deliveries stands.
- **Upgrade FAIL runs too**: rejected — see above; the existing
  contract (`test_promotion_gate_violation_fails_c6_loop`) pins a
  gate-FAIL as FAIL with "no verdict fabricated".
- **Re-run the ORACLE on ALL-PASS runs as well**: rejected — the
  ORACLE already ran in the loop; a second checker run costs up to
  900s per green run for zero signal.
- **A new `CHECKER_PASS` exit code**: rejected — exit-code semantics
  (0/2/3/4) are pinned across the harness; the label carries the
  distinction, exit 0 means the delivery passed, which is the point.

## D-681.2 — the candidate resolution contract

`resolve_candidate(ws, task_yaml, events=None)` resolves in strictly
this order:

1. **The unit's declaration wins**: `checker.candidate` (ws-relative)
   from task.yaml, used verbatim — the same face the 6 pre-existing
   declarations already rode.
2. **Otherwise the default** `artifacts/derive_reimpl.py` (the
   smoke-rehearsal shape) — legitimate exactly when its suffix matches
   the family's contract suffix (`eval_contract.candidate_suffix`, the
   single source `eval_checker._validate_candidate` grades against).
3. **A mismatch is a typed event, never a silent fallback**: the
   resolver still returns the default path (fail-open — no raise into
   the pipeline) but emits exactly one `candidate-undeclared` event
   (append-only on the caller's `events` list + one `warn`) carrying
   task_id, family, the expected suffix, and the default rel. The
   ORACLE checkpoint threads its events into the evidence detail, so
   the BLOCKED `no-candidate` stop becomes diagnosable: the run says
   WHICH contract was violated, not just that a file was missing.
4. **Unknown/unregistered family: no event.** Without a contract row
   there is nothing to judge the suffix against; a KeyError must never
   enter the pipeline (fail-open, `e2e.family_suffix` warn on any
   non-KeyError trouble).
5. **The declaration is schema-validated.** `checker.candidate` is an
   optional string in `schemas/eval-task-v1.json` and the executable
   mirror (`eval_dataset._validate_candidate_decl`): a declared
   non-string is a validation error — without it, a typo like
   `candidate: 123` slips past `resolve_candidate`'s isinstance check
   and silently falls back to the default path (the drift class the
   eval-dataset tests exist to prevent).

Declarations for the 34 tracked non-.py units follow two conventions,
both suffix-pinned to `eval_contract` by test:

- `client{suffix}` (ws-root) for re-implementation families — the
  matrix4b G3 combat contract, generalizing the existing `client.py`;
- `verdict.json` for the misdirection verdict-document families and
  `answer.txt` for the toolflex answer-document families — the graded
  artifact IS a document, named as such (the toolflex goal text says
  "produce answer.txt in the workspace root" verbatim).

The toolflex unit task.yamls are generator-owned (`eval_toolflex.
build_unit` re-mints them byte-identical); the declaration rides the
generator so the re-mint invariant holds.

### Rejected alternatives

- **Infer the path by scanning the workspace for the family suffix**:
  rejected — a guess at the contract is not a contract; multiple
  suffix-matching files make the guess arbitrary, and the checker's
  refusal class (BAD_CANDIDATE) exists precisely because the path is
  declared, not sniffed.
- **Declare `runs/deliverables/candidate{suffix}` (the loop-runner
  convention) for every unit**: rejected — the e2e combat contract is
  ws-root `client.py` (matrix4b G3 + the 6 existing declarations); the
  two harnesses keep their own conventions until a consolidation card.
- **Raise on the undeclared mismatch** (fail-closed): rejected — the
  pipeline-level posture is fail-open + one `warn`; a raise at the
  resolver would turn a labeling defect into a crash at the ORACLE
  boundary and lose the report.
