# Design: hooks/ sys.path hygiene (#671)

## D1 — Membership semantics (the core decision)

The #671 failure has TWO symptoms, and the API must fix both:

- **accumulation**: N inserts across a session leave N entries — even
  equivalent-but-differently-spelled ones, because the in-tree existence
  checks compare literal strings (`if str(dir) not in sys.path` misses
  `D:\a\..\b` vs `D:\b`);
- **reordering**: `insert(0, scripts)` in a pytest session (where pytest.ini
  `pythonpath = . hooks scripts …` already orders `hooks` BEFORE `scripts`)
  flips the ambiguous `lib_kunglao` to the scripts copy — one insert is
  enough; idempotence alone does not fix this.

Therefore:

| API | Semantics |
|---|---|
| `on_path(target)` cm | if a resolved-equal entry is already on sys.path → **no-op inside the block** (no insert, no pop, position untouched). Else insert(0), run block, finally remove exactly our entry (pop [0] if still ours, else remove the resolved-equal first match). Nested same-target: inner sees present → no-op → outer pops once. LIFO-safe for distinct targets. |
| `ensure_on_path(target)` | process-limited single action per resolved target (ledger `_ENSURED: set[str]`): absent → insert once; present → **position preserved** (this is the anti-flip half). Ledger survives later external removal (dispatch brief: "幂等单次 insert，进程内去重——记全局 flag"). |
| `ensure_on_path(target, front=True)` | #568-faithful move-to-front: remove any resolved-equal copy, insert(0). Behavior-preserving port of worker_budget.py:20's remove+insert. NOT applied anywhere else — reordering is exactly what this change removes. |
| `scripts_on_path()` / `ensure_scripts_path()` | thin convenience for `SKILL_DIR/scripts` (dominant target; names mandated by the dispatch brief). |

Normalization: `_norm(p) = str(Path(p).resolve())`; membership compares
`_norm(entry) == _norm(target)` for every sys.path entry. Wider equivalence
class than the in-tree literal checks — that is deliberate (D1 accumulation
clause). Cost: O(len(sys.path)) resolves per call — negligible at hook
frequency.

Failure containment: `on_path` never raises on cleanup (finally best-effort
removal); callers keep their existing try/except — the change is
mechanical, no error-path redesign.

## D2 — Site classification (31 sites, 13 files)

- Scoped (20) → `with on_path(...) / scripts_on_path():` — completion_gate:73;
  dispatch_gate 93/142/176/211/341/362/442/473/479; env_check_gate:155;
  lib_kunglao:308; orchestrator_tool_guard:57; state_anchor:126;
  worker_budget_gates:96/221; worker_pulse:71/135/233.
  Imported module objects used after the block are safe: bound names don't
  need the path, and every cross-import dependency of the retained modules
  (lib_kunglao → liveness_policy/env_manifest) is itself module-level
  ensure'd after this change.
- Module-level ensure (10) → `ensure_on_path` / `ensure_scripts_path()`:
  env_check_gate:54; lib_kunglao:248; recall_inject:74; session_start:20;
  state_anchor:68; worker_budget_core:42/75/100/118; write_guard:52/53.
  Repeated same-target ensures at module level (worker_budget_core ×4)
  collapse to one ledger entry.
- Front bootstrap (1) → `ensure_on_path(_HERE, front=True)`:
  worker_budget.py:20, keeping its #568 comment (order-robust bootstrap;
  the move-to-front already happens once per process today — port, not
  new policy).

## D3 — How hooks import `_path_hygiene` (bootstrap argument)

Every hook file needs `from _path_hygiene import …` BEFORE any hygiene
call, which requires `hooks/` importable. Load paths audited:

1. **Production hook subprocess** (`python …/hooks/X.py`): CPython puts the
   script's directory at `sys.path[0]` — import works, no insert needed.
2. **pytest** (`import dispatch_gate` from tests): pytest.ini `pythonpath`
   includes `hooks` — works.
3. **By-path shims** (`spec_from_file_location` in test_completion_gate,
   test_status_contract_607, …): the exec'd module body still resolves
   `import _path_hygiene` against the SESSION sys.path, which pytest
   already injected (case 2) — works.

No fourth load path exists for hooks/ in this repo (verified: no
`_entry`-style dispatcher imports hooks/ modules). Residual risk recorded
here: a hypothetical out-of-pytest embedder loading hooks by path with a
bare sys.path would ImportError — acceptable, it would fail equally on
today's sibling imports those files perform.

**D3-amendment (found in GREEN, regression-proven):** a FOURTH load path
does exist and the original audit missed it — scripts-side
`_load_worker_lib` consumers (convergence_check, backtrack_gate,
event_taxonomy, external_kicker, kunglao_status, progress_report,
reconcile_workers, scripts/lib_kunglao; all eight share the pattern) exec
`hooks/lib_kunglao.py` via `spec_from_file_location("lib_kunglao_hooks", …)`
inside `python scripts/X.py` subprocesses whose sys.path has scripts/ but
NOT hooks/. The bare `from _path_hygiene import …` then ImportErrored,
`_load_worker_lib` raises by design (#444), the convergence_check
subprocess died, `_build_pulse` got `d=None`, and the W-15 / quarantined
flags silently vanished — 4 real regressions (test_dlq_dead_letter,
test_worker_liveness W-15, test_kunglao_resume, test_trajectory_replay),
all green on base 2b7f946, all reproduced deterministically.
Fix: `hooks/lib_kunglao.py` — the ONLY hooks file on that load path —
self-bootstraps the authority by path on ImportError (registering it in
`sys.modules["_path_hygiene"]` first so every later import shares the one
instance). The eight consumers needed zero changes. heartbeat.py's
by-path load targets scripts/completion_gate.py (not hooks/) and
release_check_selfcheck / doc_sync target devkit|tools files — audited,
unaffected. A FIFTH variant surfaced at full-suite time: the subprocess
DRIVER pattern — tests/test_failopen_emit writes a tmp driver that by-path
execs hooks/dispatch_gate.py inside `python tmp/_driver.py` (sys.path has
the driver dir, not hooks/). Fixed identically: dispatch_gate.py carries
the same self-bootstrap fallback. Census of the class (current tree): all
tests spec_from_file_location uses are in-process (pytest pythonpath)
EXCEPT test_failopen_emit; scripts/ consumers are the eight above; so the
by-path-without-path set is exactly {lib_kunglao, dispatch_gate}.

## D4 — Guard design (tests/test_syspath_hygiene_671.py)

- Scanner: `re.search(r"sys\s*\.\s*path\s*\.\s*insert", line)` over
  `hooks/**/*.py`, reporting `relpath:line`.
- Whitelist: exactly `hooks/_path_hygiene.py` (the module is the sole
  insert authority; the GUARD test itself lives in tests/, outside the
  scanned root — mirroring test_no_absolute_paths.py's EXEMPT_DIRS
  precedent, but narrower: one named file, not a directory).
- Negative sample: plant `sys.path.insert(0, "x")` under tmp_path, scanner
  on that root must flag it (guard provably able to go red).
- Semantic pins (same file): (a) sys.path snapshot equality across a real
  hook entry (`completion_gate._kunglao_active` with a planted
  `.hook_state.json`, exercising the with-block import);
  (b) ensure idempotence — 3 calls → exactly one resolved entry, position
  stable when pre-present (anti-flip pin); (c) front=True move-to-front
  no-duplicate pin (#568 semantics).
- Test hygiene: the tests snapshot/restore sys.path and reset the
  `_ENSURED` ledger (monkeypatch) — the guard suite must not itself be a
  polluter.

## D5 — Relation to PR #684 (closed)

#684 fixed completion_gate with per-site by-path loading and bundled the
#608 registry gap + #535 alias (bundling is why it closed). Absorbed: the
  root-cause writeup, the by-path idea as an alternative. Rejected for the
  rollup: 31× boilerplate, per-site sys.modules cache guards, no mechanical
  guardability (see proposal "Why a hygiene module"). The registration
  table stays untouched — that is #675's domain.

## D6 — RED/GREEN plan

- RED: guard test against the pre-fix tree fails with 31 sites listed;
  semantic pins fail on missing `hooks/_path_hygiene.py` (import error).
- GREEN: implement module, migrate 31 sites, declare in
  `release-manifest.yaml`, rerun guard (0) + semantic pins + hooks-adjacent
  existing suites (test_hook*, test_wire_up*, test_gate*,
  test_worker_budget*, test_completion*, test_dispatch*, test_state_anchor*,
  test_worker_pulse*, test_env_check*…) then the 7 quality gates.
- Regression hazard watch: import order changes are the risk class; the
  #568 front bootstrap and the five literal existence checks are the only
  sites with order-sensitive behavior — both preserved by construction
  (D2).
