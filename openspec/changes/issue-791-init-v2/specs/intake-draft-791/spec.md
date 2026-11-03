# intake-draft-791 delta — issue-791-init-v2

## ADDED Requirements

### Requirement: the intake draft is confirmed before declared_ts

Init SHALL scaffold runs/intake-draft.yaml (schema intake-draft/1,
confirmed: false, declared_ts: "") carrying the classification
consequence echo (lane/project_type -> prescan battery / difficulty
factor set / capability vocabulary) and the empty distillation lists.
The goal-operationalization scaffold SHALL ship UNSTAMPED
(declared_ts: ""); the confirm face SHALL be the one stamping path. A
pre-#791 stamped goal-op SHALL never be rewritten by confirm.

#### Scenario: the un-skippable dialogue

- **WHEN** a workspace initializes and the draft is never confirmed
- **THEN** the goal-operationalization carries declared_ts: "" and the
  convergence INVALID face holds the loop until confirm

#### Scenario: the ordering pin

- **WHEN** confirm() accepts the user's answers
- **THEN** the draft records confirmed/declared_ts, the goal-op lists
  are filled and its declared_ts equals the draft's stamp

### Requirement: primary_questions are a first-class draft output

confirm() SHALL refuse an empty or malformed primary_questions set
(canonical parse — the convergence_check parser), SHALL refuse a
rubber-stamp diff_vs_verbatim (R2 vocabulary), an empty
deliverables/acceptance/not_done (R1), a double confirm, and an
unconfirmed/classification-unconfirmed answer. task_spec.yaml SHALL
receive the confirmed primary_questions when absent; a conflicting
existing set SHALL refuse the confirm.

#### Scenario: the confirm wall

- **WHEN** answers lack the explicit confirmed/classification_confirmed
  literals or carry an empty question set
- **THEN** IntakeDraftError fires and nothing is stamped

#### Scenario: R2/R5 pins stay green

- **WHEN** the goal-op validator runs on a confirmed-then-edited
  post-dispatch file
- **THEN** the constitution refusal fires exactly as before #791
