# Proposal: Hook-table count anchors derive from the registry (#675)

## Why

Every hook-registration change reddens the same three test files, and the fix
is always the same manual bump. #608 precedent (issue body): adding
`orchestrator_tool_guard.py` to the wire-up registry simultaneously broke
`test_wire_up_settings.py` (`expect 10 hook entries (got 11)`),
`test_heartbeat_bootstrap.py` (`bootstrap not idempotent`), and
`test_env_check.py` (`hooks missing`). The fix was three hand edits:
`WIRE_UP_ENTRIES` 10→11, `REGISTRY_HOOK_FILES` 9→10, `_write_settings` hook
list append. The scripts/ side already solved this class (#381
`derive_hook_subset`: hooks_selfcheck / external_kicker / heartbeat_tick
import-time-derive their file sets from `wire_up_settings.WIRE_UP_HOOK_FILES`
and loud-fail on drift) — the tests/ side never got the same treatment.

Baseline check (dev 2b7f946, post-#719): the four anchor suites
(`test_wire_up_settings.py`, `test_heartbeat_bootstrap.py`,
`test_env_check.py`, `test_hook_registry_singlesource.py`) run **61 passed** —
#719 did NOT redden any anchor. This card closes the structural drift class,
not a live regression.

## Verification table (card-mandated, all evidence from dev 2b7f946)

### Hand-pinned anchor inventory (tests/)

| # | Location | Kind | Disposition |
|---|----------|------|-------------|
| 1 | `tests/test_wire_up_settings.py:27` — `WIRE_UP_ENTRIES = 11` | full-wire-up command count | derive: `len(registry) + double-registrations` |
| 2 | `tests/test_wire_up_settings.py:29-33` — `WIRE_UP_HOOK_FILES = {...10 files}` | full registry mirror | derive: rebind to the registry import |
| 3 | `tests/test_heartbeat_bootstrap.py:47-53` — `REGISTRY_HOOK_FILES = (...)` | full registry mirror | derive: `tuple(sorted(registry))` |
| 4 | `tests/test_heartbeat_bootstrap.py:256` — `expected["worker_budget.py"] = 2` | double-registration count | derive from `DOUBLE_REGISTERED_HOOKS` |
| 5 | `tests/test_env_check.py:61-88` — `_write_settings` per-matcher groups | partial registry mirror (matcher grouping lives only in `register_hooks`' imperative sequence) | construction guard: fixture must cover exactly the registry, else raise |
| 6 | `tests/test_external_kicker.py:117-118, 343-344` — `== 3` / `== 2` | kicker re-registration table per-event split counts | derive from `KUNGLAO_HOOK_ENTRIES` |

### Correctly-retained literals (NOT drift surface — stay pinned)

| Location | Reason |
|----------|--------|
| `tests/test_hook_registry_singlesource.py:44-57` registry-content literal | sentinel: its job is pinning the registry's exact content; deriving it would be tautological (registry == registry) |
| `tests/test_kunglao_init.py:148-149` `== 1` | seed-fixture idempotency anchor — describes what `_seed_hooks_json` planted, unrelated to the registry |
| `tests/*.py` various `hooks/<file>.py` path strings | subprocess run targets for individual hooks, not registry mirrors |
| `scripts/hooks_selfcheck.KONG_HOOK_FILES`, `scripts/external_kicker.KUNGLAO_HOOK_ENTRIES` | scripts-side, already derived/pinned via `derive_hook_subset` (#381) — out of tests scope |

### Existing mechanism check (card verification items 2 and 3)

- **#685/#719 left no tests-side derivation or regeneration surface**: the
  only derivation mechanism in the repo is #381 `derive_hook_subset`
  (scripts-side consumers). #719 (2b7f946) touched `hooks/completion_gate.py`
  behavior + `ALWAYS_ARMED_HOOKS` membership; no hook-table regen exists.
  Grep evidence: no `scripts/` regen/sync tool for hook tables; 12 test
  files already `import wire_up_settings`/`hook_activation` (module import
  pattern is established) but none derives a count anchor.
- **decide() anchors are a different domain**:
  `tests/test_decide_regression_anchor.py`'s `capture_from_git_baseline` +
  `BASELINE_COMMIT` re-freeze doctrine governs *decision-function output*
  anchors. This card touches only hook-table count/file-set anchors. No
  overlap in files or mechanism.

## What Changes

1. **Registry export** (`scripts/wire_up_settings.py`): add
   `DOUBLE_REGISTERED_HOOKS = frozenset({"worker_budget.py"})` co-located
   with `WIRE_UP_HOOK_FILES` — the one structural fact (worker_budget rides
   both Pre and Post) that a pure file-count cannot express. A fresh full
   wire-up writes exactly `len(WIRE_UP_HOOK_FILES) +
   len(DOUBLE_REGISTERED_HOOKS & WIRE_UP_HOOK_FILES)` command entries.
2. **Anchor derivation** — replace the six hand-pinned points with
   registry-derived expectations (inventory above). Module-level imports via
   the established `pytest.ini` pythonpath (scripts already on path); no new
   sys.path games (conflict face with #671 left to rebase).
3. **Sentinel completion** (`tests/test_hook_registry_singlesource.py`): pin
   the new export with a literal (the one place a literal is correct).
4. **Anti-repinning guard**: a test in `test_wire_up_settings.py` asserts the
   module's own constants equal the derived formula — re-hardcoding a count
   literal fails it loudly.

## Impact

- Files: `scripts/wire_up_settings.py` (+6 lines), `tests/test_wire_up_settings.py`,
  `tests/test_heartbeat_bootstrap.py`, `tests/test_env_check.py`,
  `tests/test_external_kicker.py`, `tests/test_hook_registry_singlesource.py`.
- Risk: low — pure expectation-source change; no production behavior touched
  (the export is a constant registration code never reads today; a
  cross-reference comment is added at the `register_hooks` double-registration
  site so future editors see both).
- Acceptance (issue + card): a registry addition moves every anchor
  automatically (demonstrated RED/GREEN below); `grep` proves no hook-count
  literals remain in tests/ outside the sentinel and seed-fixture exceptions.
