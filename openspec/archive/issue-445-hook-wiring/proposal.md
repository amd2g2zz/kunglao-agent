# Hook Registration Path Unification — three paths to one canonical entry (#445)

## Why

Issue #445 (D1 mechanism proliferation, layered item L6-4): kunglao-agent
hook registration lives in THREE coexisting paths that write DIFFERENT
layers and have drifted from their own descriptions:

- Path A — `scripts/wire_up_settings.py`: the full-registry writer. Its
  historical default wrote the USER-level `~/.claude/settings.json`
  (external_kicker.py header, 2026-08-11 root-cause record: "the T1 zombie
  root cause" — hooks written where they do not fire, silently).
- Path B — `scripts/external_kicker.py::ensure_project_hooks`: a second,
  independent writer (5-entry subset) targeting the WORKSPACE-PARENT
  `.claude/settings.json`, with its own command-construction code.
- Path C — `scripts/kunglao-init.py::deploy_hooks/_patch_settings`: a third
  independent writer (worker_budget subset) with its own construction code
  and NO post-write verification.
  Plus `scripts/hook_activation.py --wire-up` — the CLI operators are told
  to run (skills/init/SKILL.md:33), which merely forwards to path A.

No path self-checks after writing. A write that lands on a layer that does
not fire produces no error (written, just silent) — the historical incident
class. Docstrings still describe dead routing (recall_inject.py:34 /
state_anchor.py:46 / env_check_gate.py:31 self-describe wirings that are
not the live entry).

## What Changes

- **`scripts/hook_activation.py` becomes THE canonical registration entry**
  (#445): `register_hooks()` (the writer, moved from wire_up_settings),
  `build_hook_entry()` (the single hook-entry construction source),
  `selfcheck_registration()` (post-write layer/coverage/shape assertion),
  and machine-readable declarations (`CANONICAL_REGISTRATION_ENTRY`,
  `DEPRECATED_ALIASES`, `DECLARED_SUBORDINATE_WRITERS`).
  `--wire-up` self-checks after writing; mismatch prints `FAIL:` and exits
  1 — the init-FAIL channel (skills/init runs exactly this CLI).
- **`scripts/wire_up_settings.py` degrades to a deprecated thin alias**: the
  `wire_up_settings()` function delegates to `hook_activation.register_hooks`
  with a `DeprecationWarning`. The REGISTRY it hosts
  (`WIRE_UP_HOOK_FILES` / `HOOK_DEPLOYMENT_TARGETS` /
  `hook_deployment_targets` / `derive_hook_subset`) stays — it is the data
  source every checker derives from (#372/#381/#410 contracts), not a
  registration entry. Alias retirement is #446, not this change.
- **`scripts/external_kicker.py`**: `ensure_project_hooks` is NOT merged
  (it is the declared dead-session bootstrap writer for the parent-level
  target, pinned by 8 tests); instead its relationship is EXPLICITLY
  declared (`REGISTRATION_RELATION` naming the canonical entry) and its
  entry construction delegates to `hook_activation.build_hook_entry`
  (byte-identical output, single construction source).
- **`scripts/kunglao-init.py`**: hook-entry construction delegates to
  `build_hook_entry`; `deploy_hooks` runs `selfcheck_registration` after
  writing; self-check mismatch fails init with the new exit code
  `RC_HOOK_WIRING = 7` (FAIL, not WARN — the issue's explicit demand).
- **Stale path descriptions corrected** (hooks/env_check_gate.py,
  hooks/recall_inject.py, hooks/state_anchor.py docstrings;
  references/cold-start-contract.md; skills/kunglao-agent/SKILL.md;
  scripts/README.md) — old names survive only as comments/aliases that
  name the canonical entry.
- **Static single-entry enforcement test**: an AST-based repo scan proves
  only `hook_activation` constructs `{"matcher": ...}` hook entries.

## Capabilities

### Modified Capabilities

- `hook-registration`: exactly one canonical entry
  (`hook_activation.register_hooks`) with post-write self-check; legacy
  names are declared aliases; the kicker is a declared subordinate
  bootstrap writer; init fails loudly on wiring self-check mismatch.

## Impact

- `scripts/hook_activation.py`: +writer/constructor/self-check/declarations
  (~200 lines, moved or new).
- `scripts/wire_up_settings.py`: writer code removed; alias + registry kept.
- `scripts/external_kicker.py`: declaration + construction delegation
  (behavior byte-identical; 8 existing tests unchanged).
- `scripts/kunglao-init.py`: construction delegation + post-write
  self-check + `RC_HOOK_WIRING = 7`.
- `tests/test_hook_registration_entry.py`: new (single-entry / self-check
  FAIL / kicker-relation pins).
- Docs: 4 docstrings + 3 md files re-pointed at the canonical entry.
- NOT in scope: #444 worker liveness protocol; #454 dormant copy;
  #446 alias retirement; kicker tick-flow self-check (residual risk,
  see design.md D7).
