## Why

Issue #99 D14: The global rule `~/.claude/rules/common/kunglao-convergence-loop.md` section 7 (hard prohibitions) has only 3 items, while `SKILL.md` "Hard prohibitions" has 5. The global rules are the always-on contract (survive `/compact`); SKILL.md loads only on explicit invocation. The missing 2 prohibitions create a security gap:

- **#4 re-plan constraint**: Without it, the orchestrator may re-plan on mere failure (violation of SKILL rule 4: re-plan only on verified finding / refutation / task_spec external update).
- **#5 VM-ONLY / HOST_FORBIDDEN_TOOLS**: Without it, after `/compact` the orchestrator may issue MCP calls that launch/attach/inject sample binaries on the host machine (e.g. `mcp__x64dbg__start_session`, `mcp__frida__spawn`). This is a **security risk** -- the `worker_budget.py` hook gates these, but only when the skill is loaded.

## What Changes

- **`scripts/check_global_rule_subset.py`** (CREATE): Mechanical parser that extracts hard prohibitions from both `SKILL.md` and `rules/kunglao-convergence-loop.md`, verifies the global rule set is a semantic subset of the SKILL set. Uses regex/keyword matching, not LLM. Exit 0 = subset satisfied; exit 1 = missing items (printed). Generic: does NOT hardcode the 2 missing items -- it will catch any future drift.
- **`tests/test_global_rule_subset.py`** (CREATE): TDD tests for the check script.
- **`.github/workflows/release-check.yml`** (MODIFY): Add a step running `check_global_rule_subset.py` to CI.
- **Unchanged**: `~/.claude/rules/common/kunglao-convergence-loop.md` (orchestrator adds missing items separately); `SKILL.md`; `hooks/worker_budget.py`.

## Capabilities

### Added Capabilities

- `global-rule-subset-check`: Mechanical validation that global-rule hard prohibitions are a semantic subset of SKILL.md hard prohibitions. Catches both current gap and future drift.

## Impact

- `scripts/check_global_rule_subset.py`: +1 script (~150 lines).
- `tests/test_global_rule_subset.py`: +1 test file (~80 lines).
- `.github/workflows/release-check.yml`: +3 lines (one CI step).
- No production code, no hooks, no rules content changed.
- CI will fail until orchestrator updates the global rules file (separate commit).
