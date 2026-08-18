# Quick Fixes — Test Isolation False-Red + wiring≠activation Output Transparency (#454)

## Why

Two unrelated defects surfaced during the 2026-08-17 audit (D1/D3 misc,
layered entries L6-2 / L1-7):

1. **Test isolation false-red (L6-2)**:
   `tests/test_init_toolchain_gate.py::test_init_gate_resolves_platform_headless`
   fails deterministically on machines whose user-level `~/.claude.json`
   carries a GLOBAL `mcp:ghidra` registration:

   ```
   AssertionError: ghidra check missing from report: [CheckResult(
     name='decompiler', status=PASS, detail='via MCP (ghidra)'), ...]
   ```

   The test clears PATH but `_check_decompiler` is MCP-first: it reads the
   REAL user registry (`mcp_probe.registered_names(mcp_probe.claude_json_path(), ws)`),
   sees `ghidra`, PASSes `decompiler` "via MCP (ghidra)" and returns — the
   independent `ghidra` CLI item the test pins never materializes. The test
   assumed an isolated registry that its own setup never created. Verified
   pre-existing by stash (the issue body records `git stash push` → still
   `1 failed` → not caused by in-flight workspace patches).

2. **wiring ≠ activation opacity (L1-7)**: both wiring surfaces print an
   "OK ... wired" line that reads as armed:

   - `scripts/kunglao-init.py:885-888` — `kunglao-init: hooks -> ... (N entries, idempotent)`
   - `scripts/hook_activation.py:297-302` — `OK: kunglao-agent hooks wired into ... (N entries)`

   But wired hooks are DORMANT by design (v1.9.7 default-inactive —
   `hooks/dispatch_gate.py:54-60`: no `.hook_state.json` → hooks sleep; the
   orchestrator activates at Phase 0 and renews the 30-min TTL). The TTL
   design is correct; the wiring output implying readiness is the defect.

## What Changes

- **`tests/test_init_toolchain_gate.py`**
  - NEW regression test simulating the hostile machine (user-global
    `mcp:ghidra` in the registry via `KUNGLAO_CLAUDE_JSON`) and asserting
    the platform-headless test still walks its expected path.
  - `test_init_gate_resolves_platform_headless` gains registry isolation:
    it injects an EMPTY user registry (`KUNGLAO_CLAUDE_JSON` → `{}`), so
    MCP-first cannot short-circuit the CLI fallback the test pins, on any
    machine. No product code changes — the MCP-first decompiler logic
    (#407) is correct and untouched.
- **`scripts/hook_activation.py`** — `--wire-up` prints a
  wired-but-dormant note naming the activation owner (orchestrator Phase 0),
  the TTL window (`DEFAULT_TTL_MINUTES`) and the renewal command.
- **`scripts/kunglao-init.py`** — the `hooks ->` deployed line is followed
  by the same wired-but-dormant semantics line (one line, same vocabulary).

## Impact

- No behavior change in the gate logic, the hook TTL mechanism, or the
  decompiler probe; output gains one transparency line per surface, tests
  gain one regression + isolation injection.
- Boundary with #445 ("registration self-check"): #454 owns ONLY the
  dormant-semantics copy at the two wiring surfaces. Any post-registration
  self-verification belongs to #445 and is NOT touched here.
- Boundary with #451/#453: none of the parked audit patches are consumed.

## Acceptance (issue #454 checkboxes)

- [ ] The platform-headless test passes on a machine with a user-global
      `mcp:ghidra` registration (isolation injection).
- [ ] init output carries hook activation semantics (wired ≠ active).
