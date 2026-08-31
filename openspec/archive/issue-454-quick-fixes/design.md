# Design — issue-454 quick fixes

## Context

- `scripts/toolchain.py:288-344` `_check_decompiler` is MCP-first (#407):
  `mcp_probe.registered_names(mcp_probe.claude_json_path(), ws)` — a
  registered `ghidra`/`ida-pro-vm` PASSes `decompiler` and RETURNS, so the
  independent `ghidra` CLI item is never emitted on such machines.
- `scripts/mcp_probe.py:135-140` `claude_json_path()` already honors the
  `KUNGLAO_CLAUDE_JSON` override ("for tests") — an established injection
  seam (the subprocess helper `_run_init` in test_init_toolchain_gate.py
  uses it, e.g. `test_init_decompiler_passes_via_ida_pro_vm_mcp`).
- `hooks/dispatch_gate.py:54-60` `_kunglao_active` — v1.9.7
  default-inactive: no state file → hooks sleep; 30-min TTL renewed by the
  orchestrator.
- `scripts/hook_activation.py:68` `DEFAULT_TTL_MINUTES = 30` is the single
  source for the TTL window.

## D1 — Test isolation via the existing `KUNGLAO_CLAUDE_JSON` seam

**Chosen**: inside `test_init_gate_resolves_platform_headless`, write an
EMPTY `{}` registry to `tmp_path` and `monkeypatch.setenv("KUNGLAO_CLAUDE_JSON", ...)`.

Why this seam and not others:

- It is the documented test override (`mcp_probe.claude_json_path`
  docstring) — no product seam is added, no monkeypatch of internal
  functions (which would survive refactorings worse).
- The workspace surface (`ws/.mcp.json`) is already isolated: the test's
  `ws` is a fresh `tmp_path` child with no `.mcp.json`.
- An empty `{}` file (rather than a nonexistent path) makes the intent
  explicit and immune to a future `_load_json` strictness change.

**Regression test** (RED first): simulate the hostile machine — write a
fake user registry containing `mcpServers: {"ghidra": ...}`, set
`KUNGLAO_CLAUDE_JSON` to it, then CALL `test_init_gate_resolves_platform_headless`
as a plain function. Pre-fix, the target test reads the hostile registry,
MCP-first short-circuits, the `ghidra` item is missing → AssertionError →
red on EVERY machine (not only ones with a real global registration — the
simulation injects the machine state deterministically). Post-fix, the
target test's inner isolation (later setenv on the same MonkeyPatch)
overrides the outer hostile registry → green.

Outer-inner interplay is safe: both use the same `monkeypatch` instance;
setenv is LIFO-undone at teardown; the inner env wins during the call,
which is exactly the semantics being pinned.

**Rejected R1**: monkeypatch `toolchain.mcp_probe.registered_names` —
patches an internal symbol, breaks silently if the implementation switches
to `check_mcp`-style plumbing, and does not exercise the real registry
resolution path the bug lives in.

**Rejected R2**: change `_check_decompiler` to always also emit the `ghidra`
item — product behavior change; the MCP-first dedup (#407) is intentional
(one decompiler item, provider named in detail).

## D2 — wired-but-dormant line at both wiring surfaces

One printed line per surface, SAME vocabulary so grepping either surface
teaches the same semantics. Content requirements (each maps to an assertion):

1. `wired` + `dormant` — the state is wired-but-not-armed (v1.9.7
   default-inactive: no `.hook_state.json` → hooks sleep).
2. activation owner — the orchestrator, at Phase 0 (`--tier`/`--set-active`).
3. TTL window — `{DEFAULT_TTL_MINUTES}-min TTL` (interpolated from the
   single source constant, never a second hardcoded 30) + `--renew` as the
   renewal command.

`scripts/hook_activation.py` (main, `--wire-up` branch) interpolates
`DEFAULT_TTL_MINUTES` directly. `scripts/kunglao-init.py` imports
`DEFAULT_TTL_MINUTES` from `hook_activation` (same scripts/ package, same
import pattern as `toolchain`/`mcp_probe`) — no new constant, no literal 30.

**Rejected R3**: make `--wire-up` also activate (write `.hook_state.json`)
— destroys the liveness signal (issue #258/#237 lineage: activation is
orchestrator-owned; subagents must not self-activate).

**Rejected R4**: put the note on stderr — it is normal-path operational
output, not a diagnostic; stdout keeps it adjacent to the OK line.

## Testing

- RED a: `test_platform_headless_isolated_from_user_global_ghidra_registration`
  (tests/test_init_toolchain_gate.py) — red pre-fix on every machine.
- GREEN a: isolation injection in `test_init_gate_resolves_platform_headless`.
- RED b: `tests/test_issue454_wiring_transparency.py`
  - `test_wire_up_output_says_wired_but_dormant` — subprocess
    `hook_activation.py <ws> --wire-up`, asserts the wired line AND the
    dormant semantics (dormant / TTL window / --renew / Phase 0).
  - `test_init_hooks_output_says_wired_but_dormant` — subprocess
    `kunglao-init.py <ws> --skip-toolchain --hooks-json <seeded>` (the
    established deploy_hooks path), same assertions.
- Quick gate: `uv run --project . python -m pytest -q -m "not load_sensitive"`
  (#369 — concurrent lanes must filter load_sensitive).
