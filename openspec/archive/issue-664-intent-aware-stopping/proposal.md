## Why

v0.1.3 milestone review: #55 completion gate stops when task-oracle items are resolved (`open=0`); #473 wired the closeout chain. **Neither checks "has the user's actual question been answered?"** — oracle items are administrative scaffolding; a session can complete with `oracle=clean` while the user's verbatim task_text mentions a concern the primary_questions never captured. The agent hits "open=0", declares done, and the user's real question is half-answered. This is the "提前宣告胜利" root cause with the oracle itself as the blind spot.

## What Changes

- **`scripts/completion_gate.py::judge()`**: new exit code 4 `INTENT_UNMATCHED` — when all oracle items are resolved (would-be PASS) but the user's `task_text` carries a content anchor that appears in NO `task_spec.yaml` primary_question text. Precedence `3 > 2 > 1 > 4 > 0` (item-remains still wins; intent fires only at the would-be-PASS point — the exact moment "done" is declared).
- **Anchor mechanics reused, not reinvented**: `premature_termination_detect._extract_anchors` (the #54 F1 task-anchor extractor — CJK runs ≥3, ASCII tokens ≥5, minus stoplist) extracts anchors from `oracle.task_text`; coverage text = concatenation of task_spec PQ ids + question text. Any anchor absent from coverage text → INTENT_UNMATCHED naming the anchor(s).
- **Workspace access follows the #147 precedent**: `judge()` already reads `oracle.workspace_path` for the global-contradiction recompute; the intent check reuses the same path to read `task_spec.yaml` (fail-open: no path / no task_spec / no PQs / no anchors → check skipped).
- **`hooks/completion_gate.py`**: NO behavior change — the Stop shim already blocks on any non-zero judge exit; docstring exit-code table gains the 4 row (contract-facing documentation only).
- **Fold-in cleanup**: `openspec/changes/issue-662-hypothesis-seed/` → `openspec/archive/` (post-#667-merge move). **CHANGELOG.md** v0.1.3 Round 3 append.

## Capabilities

### New Capabilities

- `intent-aware-completion`: the completion oracle SHALL not pass while the user's verbatim task text carries an unanswered content anchor (an anchor absent from every primary_question). Fail-open on missing PQ layer (convergence's own PQ gates own that layer).

### Modified Capabilities

- `completion-gate` (#55): exit-code family gains 4 `INTENT_UNMATCHED` (precedence 3 > 2 > 1 > 4 > 0); verdict label `INTENT_UNMATCHED` in CLI JSON output.

## Impact

- **Modified files**: `scripts/completion_gate.py` (~35 lines in judge + CLI verdict map + docstring), `hooks/completion_gate.py` (docstring only), `CHANGELOG.md`.
- **New files**: `tests/test_intent_aware_completion.py`, `openspec/changes/issue-664-intent-aware-stopping/{proposal,design,specs/.../spec,tasks}.md`.
- **Backward compatibility**: every pre-#664 oracle either has no `workspace_path` (check skipped), no task_spec (skipped), or anchors covered by its own PQs (the oracle was derived from the task) — verdicts unchanged. The check fires only in the exact defect shape it exists to catch.
- **Related**: #55 (completion gate — extends), #473 (closeout chain wiring — unchanged consumer), #54 (F1 anchor extractor — reused), #634 (loop cost burn — different layer), #662/#663 (fellow v0.1.3 Round 3).
