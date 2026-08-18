# RUNBOOK — issue #454 quick fixes (v012/issue-454-quick-fixes)

Branch `v012/issue-454-quick-fixes` off `dev` @ 6462fe4, worktree
`D:/works/kunglao-wt/454`. Reviewer/injector: read `.review/RUNBOOK.md` here,
openspec under `openspec/changes/issue-454-quick-fixes/`.

## Commits (chronological)

| SHA | Type | Content |
|---|---|---|
| 986c145 | sdd | proposal/design/tasks (mirror of archive/external-kicker shape) |
| 931ac75 | test RED-a | regression: platform-headless under simulated user-global mcp:ghidra |
| 11cea41 | fix GREEN-a | `test_init_gate_resolves_platform_headless` injects empty `KUNGLAO_CLAUDE_JSON` registry |
| 2a2e174 | test RED-b | `tests/test_issue454_wiring_transparency.py` (2 tests) |
| ed9d354 | fix GREEN-b | dormant line at `--wire-up` + init hooks output |
| (this) | docs | RUNBOOK |

Both REDs verified red at their commit: RED-a reproduced the exact issue
assertion (`ghidra check missing ... decompiler PASS via MCP (ghidra)`);
RED-b failed on `dormant`/`wired` semantics missing at both surfaces.

## Changes

1. **Test isolation (L6-2)** — `tests/test_init_toolchain_gate.py` ONLY
   (no product code):
   - `test_init_gate_resolves_platform_headless` now writes `{}` to a tmp
     file and `monkeypatch.setenv("KUNGLAO_CLAUDE_JSON", ...)` before
     `tc.check` — `mcp_probe.claude_json_path()`'s documented test override.
     MCP-first can no longer short-circuit on a machine with a user-global
     mcp:ghidra registration; the CLI-fallback `ghidra` item the test pins
     is produced on every machine.
   - New `test_platform_headless_isolated_from_user_global_ghidra_registration`:
     injects a HOSTILE registry (`mcpServers.ghidra`) via the same env var,
     then calls the target test as a function. Inner setenv (LIFO on the
     same MonkeyPatch) must override the outer hostile registry. Red on
     every machine pre-fix (deterministic simulation, no real machine
     state needed); green post-fix.
2. **wiring ≠ activation (L1-7)** — one printed line per surface:
   - `scripts/hook_activation.py` `--wire-up` branch: `NOTE: hooks wired
     but dormant — ... Phase 0 ... {DEFAULT_TTL_MINUTES}-min TTL renewed by
     --renew; no .hook_state.json -> hooks sleep`.
   - `scripts/kunglao-init.py` hooks-deployed branch: same vocabulary;
     TTL interpolated via `from hook_activation import DEFAULT_TTL_MINUTES
     as HOOK_TTL_MINUTES` (single source, no second hardcoded 30).

## Acceptance map (issue #454 checkboxes)

- [x] "该测试在'全局注册 mcp:ghidra'的机器上通过(隔离注入)" →
      `test_platform_headless_isolated_from_user_global_ghidra_registration`
      + isolation in `test_init_gate_resolves_platform_headless`.
- [x] "init 输出含 hook 激活语义说明(wired ≠ active)" →
      `test_init_hooks_output_says_wired_but_dormant` /
      `test_wire_up_output_says_wired_but_dormant`
      (`tests/test_issue454_wiring_transparency.py`).

## Gates

- Domain quick gate (init/toolchain/wire-up/activation/heartbeat-off):
  86 passed, 1 skipped (pre-existing skip) — green.
- Repo quick gate `uv run --project . python -m pytest -q -m "not
  load_sensitive"`: **1956 passed, 5 skipped, 154 deselected, 13 failed**.
  All 13 failures are PRE-EXISTING on `dev` @ 6462fe4, verified by running
  the identical files on the clean baseline worktree
  (D:/works/kunglao-agent-dev) — same 13, test-for-test:
  test_acceptance(1, cascade of test_suite_green), test_ghidra_async(4,
  NoneType), test_heartbeat_tick(2, em-dash encoding), 
  test_hook_registry_singlesource(1, ws-path), test_renderer_unify(3,
  golden drift), test_review_hook_install(2, exec-bit/NoneType). None are
  in the #454 change surface.

## Boundary compliance

- #445: untouched — no post-registration self-check added; #454 owns only
  the dormant-semantics copy.
- #451/#453: parked branch not merged; no other worktree touched.
- No push / no PR / no remote mutation (per dispatch constraints).

## Self-declared risks (for the reviewer)

1. **Outer/inner MonkeyPatch coupling** — the regression test relies on
   both layers sharing one `monkeypatch` instance and LIFO setenv override.
   If someone later splits fixtures, the test still passes standalone but
   stops simulating the hostile machine (silent weakening, not a false
   red). Mitigation: the docstring states the invariant.
2. **Output-string assertions** are keyword-level (`dormant`, `Phase 0`,
   `ttl|30`, `--renew`) — resilient to rewording but they pin vocabulary;
   a future rewrite that drops any one keyword will (intentionally) fail.
3. **init output line length** — the dormant line is long; if a consumer
   parses kunglao-init output line-by-line expecting N lines, N changed
   (only additive; no consumer found in tests/).
4. `test_hook_registry_singlesource` failure mentions a `ws/` dir under the
   repo root on BOTH trees — looks like a machine-state-sensitive test
   (repo-root `ws/` may exist from earlier local runs); pre-existing,
   out of #454 scope.
