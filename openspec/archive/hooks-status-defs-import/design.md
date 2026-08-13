# hooks-status-defs-import — Design

## Scope

Three files change, one test file gains coverage:

### Consumer changes (GREEN phase)

**hooks/worker_budget.py**
- Remove: `TERMINAL_STATUS = {'PROVEN', 'VERIFIED', 'NEGATIVE', 'REFUTED', 'DEFERRED'}` (line 26)
- Add: `from status_defs import TERMINAL` at the existing `sys.path.insert` block (line 57-62)
- Replace: all references to `TERMINAL_STATUS` with `TERMINAL` (line 622 in `check_tier_gate`)
- Keep: `TERMINAL_CLAIM_STATUSES` unchanged (different semantic: worker self-promotion guard)
- Note: `check_tier_gate` at line 617-627 uses `TERMINAL_STATUS` to decide whether a claim needs no further work. With the 8-value TERMINAL, DEAD/SUPERSEDED/STALE claims are correctly skipped.

**hooks/state_anchor.py**
- Remove: `_PARTIAL_STATUSES = {"PARTIALLY-VERIFIED", "PARTIAL", "PARTIALLY_VERIFIED"}` (line 63)
- Add: `from status_defs import PARTIAL_STATUSES` using importlib (same pattern as `_load_drift_lib`)
- Replace: `_PARTIAL_STATUSES` references with `PARTIAL_STATUSES` (lines 164, 171)

### Test changes (RED then GREEN)

**scripts/test_status_defs.py**
- Add hooks consumer filenames to CONSUMERS list:
  - `worker_budget.py` (under `hooks/` prefix)
  - `state_anchor.py` (under `hooks/` prefix)
- Expand `test_consumer_has_no_own_status_set` to handle both `scripts/` and `hooks/` paths
- Expand `test_consumer_imports_shared_module` similarly
- New parametrize: `HOOK_CONSUMERS` list with hooks files, separate path resolution

## Import mechanism

hooks/ already use `sys.path.insert(0, str(SKILL_DIR / 'scripts'))` to import scripts modules (see dispatch_gate.py:88, worker_budget.py:57, worker_pulse.py:128, state_anchor.py:113). This is the established pattern. We reuse it.

For worker_budget.py, the import is placed right after the existing sys.path.insert at line 57, inside the same try/except block that imports priority.py. This ensures `status_defs` is available at module load time (not deferred).

For state_anchor.py, the import uses importlib.util (same pattern as _load_drift_lib at line 70) because state_anchor.py avoids top-level sys.path mutations in its current design. However, since state_anchor.py already does `sys.path.insert(0, str(SKILL_DIR / "scripts"))` at line 113 inside `_kunglao_active`, we can do the import at module level with a simple import after the sys.path insert, or via a deferred helper. Given the file's FAIL_OPEN philosophy, a deferred import with caching (same as _load_drift_lib) is the safest approach. Alternatively, since `_PARTIAL_STATUSES` is used only in `_register_open_ids` (called at runtime, not import time), we can import it there.

Simplest correct approach: add the import at the top of state_anchor.py using the same sys.path + import pattern, since the constant is needed at module level for regex-style usage.

Actually, looking more carefully: `_PARTIAL_STATUSES` is used at lines 164 and 171 inside `_register_open_ids` which is called from `_open_ids` called from `build_anchor`. So it's only needed at runtime. The cleanest approach: import status_defs.PARTIAL_STATUSES lazily inside `_register_open_ids` or at module level with sys.path.

Decision: import at module level with sys.path (consistent with other hooks), with a try/except FAIL_OPEN fallback to the hardcoded set (so the hook never breaks even if status_defs is missing).

Wait — the whole point of the fix is to REMOVE the hardcoded fallback. If status_defs is unavailable, the 3-value PARTIAL_STATUSES is still correct (it hasn't changed). But the principle is: import from status_defs or fail. Given the hook's FAIL_OPEN philosophy, we'll import at module level with a try/except that falls back to the old value but logs a warning. This is acceptable because:
1. The test guard ensures the import exists in the source.
2. Runtime failure mode preserves existing behavior.

Actually, simpler: just do the import alongside the existing sys.path.insert at the top of the file (after SKILL_DIR is defined). Since state_anchor.py already has `SKILL_DIR = Path(__file__).resolve().parent.parent` at line 59, we can add the import right after.

## Guard extension

The CONSUMERS list in test_status_defs.py currently only contains scripts/ filenames. We add a parallel HOOK_CONSUMERS list for hooks/ files. Both test functions get parametrized over the union, with path resolution that prefixes `scripts/` or `hooks/` appropriately.

## Regression boundary

- status_defs.py TERMINAL 8-value set: UNCHANGED
- TERMINAL_CLAIM_STATUSES in worker_budget.py: UNCHANGED (different concept)
- All other hooks (dispatch_gate, worker_pulse, completion_gate, agent_watch, heartbeat_touch, lib_kunglao): UNCHANGED (no local status sets to fix)
- Existing test expectations: UNCHANGED
