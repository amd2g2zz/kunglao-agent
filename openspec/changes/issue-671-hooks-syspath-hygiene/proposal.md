# Proposal: hooks/ sys.path.insert hygiene — scoped + idempotent membership, zero bare inserts (#671)

## Problem

`hooks/` modules bootstrap sibling imports (scripts/ helpers, hooks/ peers)
with `sys.path.insert(0, <dir>)` and never clean up. Fine for the
short-lived hook subprocess of production; in a long-lived pytest session
every insert persists across all later collection and runtime, and each
entry at `sys.path[0]` re-orders module resolution for the ambiguous
`lib_kunglao` name (hooks/ and scripts/ both ship one), producing the
observed `ImportError: cannot import name scan_active_workers from
lib_kunglao (…scripts\lib_kunglao.py)` cascade (#671 symptom).

Count basis (all three recorded, actual-verified wins):

| Source | Count | Basis |
|---|---|---|
| Issue #671 body | 11 | manual list at filing time (completion_gate:68 already fixed in-session) |
| Dispatch brief | 32 | pre-dispatch sweep |
| **Actual, dev `2b7f946` (this worktree)** | **31** | `grep -rn "sys\.path\.insert" hooks/` — 13 files; wide variant `sys\.path\s*\.\s*insert` also 31 |

The 31 sites split into three shapes:

1. **module-level long-lived** (10) — insert at import time, entry stays for
   the process (env_check_gate:54, lib_kunglao:248, recall_inject:74,
   session_start:20, state_anchor:68, worker_budget_core:42/75/100/118,
   write_guard:52/53);
2. **function-scoped** (20) — insert inside a try, import a sibling, return
   (completion_gate:73, dispatch_gate ×8, env_check_gate:155,
   lib_kunglao:308, orchestrator_tool_guard:57, state_anchor:126,
   worker_budget_gates:96/221, worker_pulse:71/135/233);
3. **order-robust bootstrap** (1) — worker_budget.py:20 removes-then-reinserts
   `hooks/` at `sys.path[0]` on purpose (#568: an earlier scripts/ entry
   winning would resolve `lib_kunglao` to the scripts copy that lacks
   `scan_active_workers`). This one is NOT a leak — its move-to-front
   semantics must be preserved, not "fixed".

Five sites already carry a partial `if dir not in sys.path` existence check
(dispatch_gate:93, env_check_gate:54, lib_kunglao:248/308,
worker_budget_core:42) — the existence-check instinct exists in-tree but is
uncentralized, literal-string based (misses equivalent-but-unresolved
spellings, so duplicates still accumulate), and never pops scoped entries.

## Solution

1. **New module `hooks/_path_hygiene.py`** (single source for path
   membership):
   - `on_path(target)` contextmanager — scoped membership: insert on enter,
     pop on exit (try/finally); **already-present targets are untouched —
     no reordering, no pop** (reordering is the other half of the #671
     bug: pytest.ini puts `hooks` before `scripts`, and an insert(0)
     flip is what broke `lib_kunglao`);
   - `scripts_on_path()` — `on_path(SKILL_DIR/scripts)` convenience (the
     dominant target);
   - `ensure_on_path(target, *, front=False)` — idempotent process-wide
     membership: first call for an absent dir inserts once and records it
     in a module-level ledger (`_ENSURED`); already-present dirs are left
     in place (position preserved); `front=True` is the #568-faithful
     move-to-front variant (remove any copy, insert at 0);
   - `ensure_scripts_path()` — `ensure_on_path(SCRIPTS_DIR)` convenience.
2. **All 31 sites migrate**: 20 function-scoped → `with on_path(...) /
   scripts_on_path():`; 10 module-level → `ensure_on_path(...)` /
   `ensure_scripts_path()`; worker_budget.py:20 →
   `ensure_on_path(_HERE, front=True)` (semantics preserved, comment kept).
3. **Guard** `tests/test_syspath_hygiene_671.py`: scan `hooks/**/*.py` for
   bare `sys.path.insert` — must be 0; whitelist is exactly
   `hooks/_path_hygiene.py` (the module IS the insert authority), with a
   planted-violation negative sample proving the guard can go red
   (pattern follows `tests/test_no_absolute_paths.py` + its EXEMPT_DIRS
   precedent). Same file pins the two API semantics: sys.path unchanged
   across a scoped use (real hook entry `completion_gate._kunglao_active`),
   ensure idempotence (repeat calls → exactly one entry, position stable).
4. **Release manifest**: `hooks/_path_hygiene.py` is declared in
   `release-manifest.yaml` (new shipped asset; CI fails undeclared files).

## Why a hygiene module and not per-site by-path loads

PR #684 (closed) fixed one site with `importlib.util.spec_from_file_location`
(zero sys.path side effects). Absorbed and rejected as the rollup shape:
31 sites × ~5 lines of spec boilerplate duplicates a mechanism 31 times,
defeats the module cache (`sys.modules[name]` guards needed per site), and
cannot be guarded mechanically. A single 4-function module gives one
testable seam, one whitelist entry for the guard, and keeps every call site
a one-line change. Trade-off accepted: `import _path_hygiene` itself needs
`hooks/` importable — true in every real load path (hook subprocess: script
dir auto-prepended; pytest: pytest.ini `pythonpath` includes `hooks`;
by-path shims in tests: exec inside a pytest session that already injected
`hooks`). Recorded as design D3.

## Out of scope

- Hook registration/wiring logic (#675 domain) — no site in this change
  touches registration tables; import mechanics only.
- The #608 registry gap and #535 `_entry` alias riding PR #684 — not
  bundled (single responsibility; #684 was closed for bundling them).
- `scripts/` and `tools/` trees — no bare-insert census reported there by
  the issue; guard scope stays `hooks/`.
- pytest.ini `pythonpath` itself — the session-level injection is the
  ambient contract the hygiene semantics must respect, not fight.

## What changes

- ADD `hooks/_path_hygiene.py`
- EDIT 13 hook files (31 sites): completion_gate, dispatch_gate (9),
  env_check_gate (2), lib_kunglao (2), orchestrator_tool_guard,
  recall_inject, session_start, state_anchor (2), worker_budget (1),
  worker_budget_core (4), worker_budget_gates (2), worker_pulse (3),
  write_guard (2)
- ADD `tests/test_syspath_hygiene_671.py`
- EDIT `release-manifest.yaml` (declare the new hook asset)
- Issue #671 comment: 11 (filed) vs 32 (dispatch sweep) vs 31 (actual,
  dev 2b7f946) count reconciliation
