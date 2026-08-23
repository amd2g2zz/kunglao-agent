# Design — hook registration path unification (#445)

Context: issue #445 evidence chain (three registration paths, layer drift,
silent mis-layer writes). Proposal: `../proposal.md`. This file answers the
three design questions the milestone asked for: who is the single writer,
how the legacy names degrade, and how the layer self-check fails init.

## D1 — THE single writer: `hook_activation.register_hooks`

`scripts/hook_activation.py` is upgraded from a CLI forwarder to the
canonical registration entry. It gains, in one module:

- `build_hook_entry(hook_dir, hook_file, matcher)` — THE hook-entry
  construction source (`{"matcher": ..., "hooks": [{"type": "command",
  "command": "uv run --project <skill_root> <hooks>/<file>"}]}`, POSIX
  paths, #389 uv form). Byte-identical to the shapes wire_up_settings,
  external_kicker and kunglao-init each hand-rolled before — all three now
  call this one function.
- `register_hooks(workspace=None, global_opt_in=False) -> int` — the writer,
  moved verbatim from `wire_up_settings.wire_up_settings` (#258 project
  target, #269 canonical command paths, #389 uv form, idempotent merge).
  After writing it runs the self-check (D5) and raises
  `HookWiringSelfcheckError` on mismatch (fail-closed).
- `selfcheck_registration(target, *, expected_files, hook_dir=None,
  workspace=None, layer="project")` — the post-write assertion (D5).
- Declarations (machine-readable, pinned by tests):
  `CANONICAL_REGISTRATION_ENTRY = "hook_activation.register_hooks"`,
  `DEPRECATED_ALIASES`, `DECLARED_SUBORDINATE_WRITERS`.

Why hook_activation and not wire_up_settings: the CLI operators are already
told to run is `hook_activation.py <ws> --wire-up` (skills/init/SKILL.md,
cold-start-contract Phase 0) — the entry that must gain the FAIL semantics
is the one on the operator's path. wire_up_settings keeps no writer code.

`main() --wire-up` maps `HookWiringSelfcheckError` to stderr
`FAIL: hook wiring selfcheck — <mismatches>` + exit 1 (was: always 0).
This is the init-FAIL channel: skills/init runs exactly this command, and
`hooks_selfcheck.rebuild_project_level` already propagates its rc.

## D2 — wire_up_settings degrades to a deprecated alias; callers migrate

`wire_up_settings()` keeps its exact signature `(workspace=None,
global_opt_in=False) -> int`, emits a `DeprecationWarning` naming
`hook_activation.register_hooks` (#445; retirement is #446), and delegates.
pyproject already ignores DeprecationWarning in pytest, so existing test
callers (test_wire_up_settings.py, test_completion_gate.py) stay green.

The REGISTRY stays in wire_up_settings: `WIRE_UP_HOOK_FILES`,
`HOOK_DEPLOYMENT_TARGETS`, `hook_deployment_targets`, `derive_hook_subset`.
It is the data source env_check / external_kicker / hooks_selfcheck / the
singlesource tests derive from (#372/#381/#410 contracts) — moving it would
churn four importers for zero convergence (the proliferation being fixed is
WRITERS, not the registry). Keeping it also preserves the
test_heartbeat_tick scratch-skill drift mechanism (registry rename →
derive_hook_subset raises at import).

Caller migration: `hook_activation.main --wire-up` calls `register_hooks`
directly (no longer imports the alias). No other production caller of the
function object exists; remaining references are tests (allowed — they
exercise the alias) and comments.

## D3 — external_kicker.ensure_project_hooks: declared subordinate, shared construction

NOT merged. The kicker is the dead-session BOOTSTRAP writer: it must write
the WORKSPACE-PARENT target (`hook_deployment_targets[1]`, #410) with a
deliberately narrow 5-entry subset while a session is dead — merging it
into the full-registry ws-level writer would change recovery behavior and
break the 8 `test_ensure_project_hooks_*` pins. Acceptance 3 explicitly
allows "或显式声明关系". The relationship becomes mechanical:

1. `REGISTRATION_RELATION` constant in external_kicker.py —
   `canonical_entry` MUST equal `hook_activation.CANONICAL_REGISTRATION_ENTRY`
   (test-pinned), with `role`, `target`, and `subset` fields documenting the
   bootstrap contract.
2. Its `_canonical` entry construction is replaced by a call to
   `hook_activation.build_hook_entry` — the third hand-rolled constructor
   disappears; the kick path and the canonical path can no longer drift
   apart in command shape (test-pinned byte-equality).

Top-level `import hook_activation` in external_kicker is safe: the
canonical module imports no siblings at module scope (lazy imports only),
so no cycle exists in either direction.

## D4 — kunglao-init: canonical construction + self-check → RC_HOOK_WIRING

init's `_ensure` keeps its replace-legacy-in-place fixed-point logic but
constructs entries via `build_hook_entry` (its sys.path already carries
scripts/). `deploy_hooks` runs `selfcheck_registration` after every write:

- default target (`<ws>/.claude/settings.json`, only when it already
  exists) → `layer="project"` (must be a declared deployment target);
- `--hooks-json` target → `layer="operator-declared"` (the operator named
  the file; coverage + shape still asserted, layer membership not).

Mismatch → `initialize()` returns the new `RC_HOOK_WIRING = 7` (FAIL, not
WARN — the issue's explicit requirement; the skip path — no settings file
present — remains a benign skip, since nothing was written there is nothing
to mis-layer). The report→rc mapping lives in the tiny pure
`hook_deploy_rc(report)` so the FAIL semantics are directly testable.

## D5 — the layer self-check (写入位置 vs 实际 fire 层级)

`selfcheck_registration` re-reads the WRITTEN FILE from disk (maker-checker:
never trust the in-memory dict the writer just built) and asserts:

1. **Layer** (the #445 core): with `layer="project"`, the resolved target
   must be a member of `wire_up_settings.hook_deployment_targets(workspace)`
   AND must not be the user-global `~/.claude/settings.json` — a write
   outside the declared fire layers is the historical "repaired the wrong
   file" bug. `layer="user-opt-in"` (global_opt_in) must BE the user-global
   file. `layer="operator-declared"` skips membership (explicit choice)
   but keeps 2 and 3.
2. **Coverage**: every `expected_files` basename appears as a command
   basename in the re-read file (Pre/Post/Stop all scanned) — the v1.9.37
   "settings rewrite dropped the hooks segment" class.
3. **Shape**: every expected command is `uv run --project <skill_root>`
   pointing into the declared `hook_dir` (default: the canonical deployed
   skill dir) — the #269 worktree-bound-command silent-death class.
   Path EXISTENCE is deliberately not asserted (canonical installs under a
   monkeypatched HOME are a legitimate test fixture shape).

Returns `{"ok": bool, "mismatches": [...], "present": [...], "missing":
[...]}`; never raises — the caller decides the failure mode
(register_hooks raises; init maps to RC_HOOK_WIRING; the CLI prints FAIL
and exits 1). The historical bug is reproduced in the RED suite by
monkeypatching the `_resolve_registration_target` seam (D6) to return the
user-global path: the CLI must FAIL, not print OK.

## D6 — single-entry enforcement is static and mechanical

A test parses every `scripts/*.py` + `hooks/*.py` with `ast`, strips
docstrings (module/function/class), and asserts the construction signature
`'"matcher":'` appears ONLY in `hook_activation.py`. Today it also appears
in wire_up_settings / external_kicker / kunglao-init — the RED proof of
"three (four sites) writers". Docstring examples (5 hooks modules) are
stripped, so they cannot false-positive. Declaration tests pin
`CANONICAL_REGISTRATION_ENTRY`, alias delegation (monkeypatched recorder),
and the kicker's `REGISTRATION_RELATION`. This is the repo's
single-source-pin style (test_hook_registry_singlesource.py) applied to
writers instead of lists.

Seams (testability, repo convention): `_resolve_registration_target` in
hook_activation (layer-mismatch injection), standard monkeypatch for
`selfcheck_registration` when testing propagation-only paths.

## D7 — rejected alternatives / deliberate non-changes

- Merging the kicker writer into register_hooks — recovery behavior change,
  breaks 8 pins; declaration + shared constructor achieves convergence.
- Moving the registry out of wire_up_settings — churn without convergence.
- Deleting the legacy names — forbidden (conservative migration; #446).
- Self-check inside the kicker's `tick()` — the kicker is a declared
  subordinate whose transform is already fixed-point-pinned; adding a
  check there risks the tick flow for no acceptance gain. Residual risk,
  recorded in the RUNBOOK.
- init canonicalizing its hook_dir to the deployed skill dir (#269 class)
  — behavior change beyond #445; init's self-check verifies against the
  dir init actually used (documented residual).
