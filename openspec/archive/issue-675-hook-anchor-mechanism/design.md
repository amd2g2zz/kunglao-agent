# Design — Hook-table count anchors derive from the registry (#675)

## D0. Decision matrix

| Decision | Choice | Rejected alternative | Why |
|----------|--------|---------------------|-----|
| D1 | Export `DOUBLE_REGISTERED_HOOKS` from `wire_up_settings.py` | bare `+ 1` arithmetic in each test | the `+1` is a named structural fact; a bare literal in tests is the same hand-pin in smaller clothes. Co-located with the registry so a registration editor sees both constants |
| D2 | Tests import the registry at module level (`pytest.ini` pythonpath already lists `scripts`) | per-test `sys.path.insert` + function-level import | the module-level pattern is already established (12 test files import `wire_up_settings`/`hook_activation`); avoids touching import regions #671 is reworking |
| D3 | `_write_settings` keeps its per-matcher groups, gains a construction guard | restructure to call the real `register_hooks` writer | the matcher grouping lives only in `register_hooks`' imperative `_ensure` sequence; the fixture calling the real writer changes test semantics (fixture → integration) and couples env_check tests to deployment machinery. The guard converts silent drift into a loud fixture-construction failure naming the symmetric difference |
| D4 | `test_external_kicker` counts derived from `KUNGLAO_HOOK_ENTRIES` | out-of-scope "kicker is a different table" | same drift class (hook-table count literal), trivially derivable from an existing declarative table; the acceptance grep must come back clean |
| D5 | Sentinel literal stays in `test_hook_registry_singlesource.py` (and pins the new export) | derive the sentinel too | a sentinel comparing the registry to itself proves nothing; the literal is the load-bearing loud-fail on registry growth (#381 contract) |
| D6 | Anti-repinning guard asserts the test module's own constants match the derivation formula | rely on grep alone | grep is the acceptance evidence, the guard is the durable in-CI tripwire; re-hardcoding fails a named test instead of a repo policy doc |

## D1. The count formula (single source of truth)

```
expected_commands = len(WIRE_UP_HOOK_FILES) + len(DOUBLE_REGISTERED_HOOKS & WIRE_UP_HOOK_FILES)
```

- `WIRE_UP_HOOK_FILES` — 10 files today (`scripts/wire_up_settings.py:55`).
- `DOUBLE_REGISTERED_HOOKS` — `{"worker_budget.py"}` today: `register_hooks`
  issues 11 `_ensure`/`_ensure_stop` calls; worker_budget appears under
  Pre/Agent AND Post/Agent. Every other file lands exactly once
  (heartbeat_touch + orchestrator_tool_guard under Pre/Bash, write_guard
  under Pre/Edit|Write|MultiEdit, completion_gate under Stop — all count 1).
- The `& WIRE_UP_HOOK_FILES` intersection makes the formula self-correcting:
  a stale double-registered name removed from the registry stops inflating
  the expectation instead of corrupting it.
- Cross-reference comment added at the `register_hooks` double-registration
  site (worker_budget Post) pointing at the export — future editors of the
  registration sequence see the derived-consumer contract. No behavior
  change: `register_hooks` does not read the export.

## D2. Per-file derivation plan

| File | Before | After |
|------|--------|-------|
| `tests/test_wire_up_settings.py` | `WIRE_UP_ENTRIES = 11`; hand set | `import wire_up_settings`; `WIRE_UP_HOOK_FILES = wire_up_settings.WIRE_UP_HOOK_FILES`; `WIRE_UP_ENTRIES = len(...) + len(...)` per D1; + anti-repinning test (D6) |
| `tests/test_heartbeat_bootstrap.py` | hand tuple; `expected["worker_budget.py"] = 2` | `REGISTRY_HOOK_FILES = tuple(sorted(wire_up_settings.WIRE_UP_HOOK_FILES))` (sorted → deterministic failure messages); expected counts derived as `1 + (f in DOUBLE_REGISTERED_HOOKS)` |
| `tests/test_env_check.py` | hand per-matcher groups | groups unchanged; `_write_settings` ends with a guard: collect referenced basenames, `raise AssertionError` naming `sorted(covered ^ registry)` on mismatch |
| `tests/test_external_kicker.py` | `== 3` / `== 2` ×2 | `from external_kicker import KUNGLAO_HOOK_ENTRIES`; `KICKER_PRE = sum(1 for e, _, _ in KUNGLAO_HOOK_ENTRIES if e == "PreToolUse")` etc. |
| `tests/test_hook_registry_singlesource.py` | registry sentinel only | + sentinel pin for `DOUBLE_REGISTERED_HOOKS` (D5) |

## D3. RED/GREEN proof protocol (drift-elimination demonstration)

The drift class is "a proper registration change (registry entry + `_ensure`
call) reddens hand-pinned anchors". Demonstrated on a scratch edit, never
committed:

1. Add `"zz_fake_probe_675.py"` to `WIRE_UP_HOOK_FILES` AND a matching
   `_ensure` call in `register_hooks` (simulating the #608-shape change done
   correctly).
2. **RED run** (before this card's fix): the three suites fail with count and
   basename mismatches — the exact #608 signature.
3. **GREEN run** (after derivation, same scratch edit re-applied): all anchor
   tests pass with zero test-file edits — the expectation moved with the
   registry.
4. Revert the scratch edit; full anchor suites return to 61-passed baseline.

Separately and durably: the D6 guard keeps the derivation property under CI.

## D4. Scope fence

- Not touched: `tests/test_decide_regression_anchor.py` (different domain —
  decision-output anchors with their own re-freeze doctrine), scripts-side
  `derive_hook_subset` consumers (already derived), `tests/test_kunglao_init.py`
  seed-fixture counts (describe the seed, not the registry), hooks/ files
  (#671 conflict face).
- No production behavior change; `scripts/wire_up_settings.py` gains one
  constant and one comment block only.
