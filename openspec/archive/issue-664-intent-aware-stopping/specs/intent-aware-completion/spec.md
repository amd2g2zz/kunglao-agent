## ADDED Requirements

### Requirement: Completion gate SHALL refuse PASS while the user's task text carries an unanswered anchor

When the oracle's items are all resolved (the would-be-PASS point), `judge()` SHALL extract content anchors from `oracle.task_text` (reusing the #54 F1 extractor) and verify every anchor appears in the concatenated text of `task_spec.yaml` primary_questions (ids + question text). Any anchor absent from that coverage text SHALL produce exit 4 `INTENT_UNMATCHED` with the unmatched anchors named in the reason. Precedence SHALL remain 3 > 2 > 1 > 4 > 0.

#### Scenario: user concern missing from the PQ set
- **WHEN** oracle items are all closed, deferrals user-signed, and `task_text` mentions a concern whose anchor appears in no primary_question
- **THEN** judge returns `(4, "INTENT_UNMATCHED ... <anchor> ...")` and the Stop shim blocks termination

#### Scenario: anchors fully covered
- **WHEN** every task_text anchor appears in some PQ's id or question text and the oracle is otherwise clean
- **THEN** judge returns `(0, PASS ...)` — verdict unchanged from pre-#664 behavior

#### Scenario: item-level defects outrank intent
- **WHEN** oracle has unresolved items AND an unmatched anchor
- **THEN** judge returns exit 1 (INCOMPLETE) — item-remains keeps priority over intent

### Requirement: The intent check SHALL fail open on a missing PQ layer

The check SHALL be skipped (never block) when the oracle carries no `workspace_path`, the workspace has no `task_spec.yaml`, the task_spec is malformed or has no primary_questions, the task_text yields zero anchors, or the anchor module is unimportable.

#### Scenario: pre-#147 oracle without workspace_path
- **WHEN** judge receives a clean oracle with no `workspace_path` key
- **THEN** judge returns PASS — the intent check is skipped

#### Scenario: workspace without task_spec
- **WHEN** `workspace_path` points at a directory with no `task_spec.yaml`
- **THEN** judge returns the items-driven verdict unchanged, no crash

### Requirement: CLI verdict label

`scripts/completion_gate.py` CLI JSON output SHALL map exit 4 to the verdict label `INTENT_UNMATCHED`.

#### Scenario: CLI invocation on an unmatched oracle
- **WHEN** `python scripts/completion_gate.py <task-oracle.yaml>` is run on an oracle triggering the intent check
- **THEN** stdout JSON carries `"exit_code": 4` and `"verdict": "INTENT_UNMATCHED"`

### Requirement: Stop-shim propagation unchanged

`hooks/completion_gate.py::process_event` SHALL continue to block termination on ANY non-zero judge exit; exit 4 SHALL propagate through the existing code path with no logic change (docstring exit-code table updated to document the new row).

#### Scenario: Stop event on intent-unmatched workspace
- **WHEN** the Stop shim invokes judge on an activated workspace whose oracle returns 4
- **THEN** the shim emits `{"decision": "block", ...}` and returns 4
