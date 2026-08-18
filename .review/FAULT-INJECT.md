# FAULT-INJECT — issue #454 quick fixes (adversarial injection report)

- Injector: independent subagent (maker-checker adversarial slot; NOT the implementer)
- Worktree `D:/works/kunglao-wt/454`, branch `v012/issue-454-quick-fixes` @ `bc0aa27`
- Protocol: each mutation applied to the dirty working tree ONLY → targeted test run
  → result recorded (RED = kill / GREEN = survivor) → `git checkout -- <file>` restore
  → next shot. No commit, no push, branch head never moved.
- Test runner: `.venv/Scripts/python.exe -m pytest -q -m "not load_sensitive"`
  (venv python used directly after first sync to avoid `uv run` re-dirtying uv.lock)

## Kill-rate summary

| # | Mutation | Target | Verdict |
|---|---|---|---|
| a | delete in-test `KUNGLAO_CLAUDE_JSON` isolation injection (revert core of 11cea41), pass-through real machine registry | `tests/test_init_toolchain_gate.py` | **KILL** (2 tests red) |
| b1 | delete dormant NOTE block (8 lines) from `scripts/hook_activation.py` --wire-up | product | **KILL** |
| b2 | delete dormant block (8 lines) from `scripts/kunglao-init.py` hooks-deployed | product | **KILL** |
| c1 | `dormant` → `inactive` (`hook_activation.py` NOTE) | vocabulary pin | **KILL** |
| c2 | `--renew` → `--refresh` (`kunglao-init.py` dormant line) | vocabulary pin | **KILL** |
| c3 | `TTL` → `timeout` (`hook_activation.py` NOTE) | vocabulary pin | **SURVIVED** |
| c4 | `Phase 0` → `startup phase` (`kunglao-init.py` dormant line) | vocabulary pin | **KILL** |

**kill-rate = 6/7 ≈ 85.7% ≥ 1/3 → PASS** (per plan Task 4 line).

## Mutations, detail

### a — delete test-isolation injection (GREEN-a revert core)

- Change: removed the 9-line block in
  `tests/test_init_toolchain_gate.py::test_init_gate_resolves_platform_headless`
  (comment + `isolated_registry` write + `monkeypatch.setenv("KUNGLAO_CLAUDE_JSON", ...)`)
  → the test now passes the REAL machine registry through (exactly pre-11cea41 behavior).
- Commands + results:
  - `pytest -q tests/test_init_toolchain_gate.py::test_platform_headless_isolated_from_user_global_ghidra_registration`
    → **1 failed** — `AssertionError: ghidra check missing from report` (931ac75's
    regression net caught the removed isolation deterministically: outer hostile
    registry + no inner override → MCP-first short-circuit).
  - `pytest -q tests/test_init_toolchain_gate.py::test_init_gate_resolves_platform_headless`
    → **1 failed** on THIS machine — pass-through of the real `~/.claude.json`
    (verified: its top-level mcpServers include a global `ghidra`) reproduces the
    original issue #454 false-red verbatim (`ghidra check missing ... decompiler
    PASS via MCP (ghidra)`).
- Verdict: **KILL** (double). The regression test is NOT vacuous — 11cea41 is load-bearing.
- Restore: `git checkout -- tests/test_init_toolchain_gate.py` → 2 passed.

### b1 — delete dormant line, `--wire-up` surface

- Change: deleted the 8-line `#454` comment + `NOTE: hooks wired but dormant ...`
  print from `scripts/hook_activation.py` main() --wire-up branch.
- Command: `pytest -q tests/test_issue454_wiring_transparency.py::test_wire_up_output_says_wired_but_dormant`
- Result: **1 failed** — `wired-but-DORMANT state not stated`.
- Verdict: **KILL**. Restore → 1 passed.

### b2 — delete dormant line, init surface

- Change: deleted the 8-line `#454` comment + `kunglao-init: hooks wired but
  dormant ...` print from `scripts/kunglao-init.py` initialize().
- Command: `pytest -q tests/test_issue454_wiring_transparency.py::test_init_hooks_output_says_wired_but_dormant`
- Result: **1 failed** — `wiring line missing` (the surface's only "wired" wording
  lives in the dormant line; deleting it kills at the FIRST keyword assert).
- Verdict: **KILL**. Restore → 1 passed.

### c1 — vocabulary pin: `dormant`

- Change: `NOTE: hooks wired but dormant` → `... but inactive` (`hook_activation.py`).
- Result: test_wire_up **1 failed** at the `dormant` assert → **KILL**. Restore → green.

### c2 — vocabulary pin: `--renew`

- Change: `-min TTL renewed by --renew` → `-min TTL renewed by --refresh` (`kunglao-init.py`).
- Result: test_init_hooks **1 failed** — `renewal command (--renew) not named` → **KILL**. Restore → green.

### c3 — vocabulary pin: `TTL` (SURVIVOR)

- Change: `-min TTL renewed by --renew` → `-min timeout renewed by --renew` (`hook_activation.py`).
- Result: test_wire_up **1 passed** — the assert is `"ttl" in low or "30" in out`
  and the mutated output still carries `30-min timeout` (DEFAULT_TTL_MINUTES
  interpolation), so the OR-escape accepts it.
- Analysis: NOT a vacuous net — the TTL *window information* (30 minutes) is still
  communicated by the number; the pin anchors "word ttl OR literal 30". It is
  however a deliberately weak single-keyword pin, matching RUNBOOK self-declared
  risk ② (`ttl|30`). Noted as the one accepted survivor. If the constant ever
  changes away from 30 AND the word TTL is dropped, the assert would fail.
- Verdict: **SURVIVED** (documented, accepted).

### c4 — vocabulary pin: `Phase 0`

- Change: `orchestrator-owned (Phase 0, ...)` → `orchestrator-owned (startup phase, ...)`
  (`kunglao-init.py`).
- Result: test_init_hooks **1 failed** — `activation owner (orchestrator Phase 0)
  not named` → **KILL**. Restore → green.

## Negative cases (original fault scenarios from the issue)

### N1 — "user-global mcp:ghidra registered" machine (issue failure scenario)

- **N1a pre-fix failure path (raw toolchain level, no repo edits)**: hostile fake
  registry `{"mcpServers":{"ghidra":{...}}}` via `KUNGLAO_CLAUDE_JSON`, fake
  platform-correct analyzeHeadless under GHIDRA_HOME, empty PATH → `toolchain.check`:
  `decompiler PASS via MCP (ghidra)` + `HAS_GHIDRA_ITEM=False` — byte-for-byte the
  issue's failure signature. Also confirmed the REAL `~/.claude.json` on this host
  carries a global `ghidra` registration (machine truly is the hostile machine).
- **N1b post-fix path**: same setup + in-test empty-registry override →
  `ghidra PASS analyzeHeadless at ...\support\analyzeHeadless.bat`,
  `HAS_GHIDRA_ITEM=True`, `mcp:ghidra` correctly FAIL (not registered) — the exact
  path the test pins.
- **N1c process-level hostile env + fixed tests**: `KUNGLAO_CLAUDE_JSON=<hostile>`
  exported into the pytest process itself → both
  `test_init_gate_resolves_platform_headless` and
  `test_platform_headless_isolated_from_user_global_ghidra_registration`
  **2 passed** (inner monkeypatch LIFO override wins over the outer hostile env).
  Acceptance checkbox "该测试在'全局注册 mcp:ghidra'的机器上通过(隔离注入)" → **PASS**.

### N2 — wire-up/init output with NO `.hook_state.json` (dormant semantics)

- `hook_activation.py --wire-up` on a fresh ws: rc=0, output contains
  `hooks wired but dormant`, the explicit clause `no .hook_state.json -> hooks sleep`,
  and wiring creates **no** `.hook_state.json` (dormancy is real, not just claimed).
- `kunglao-init.py --skip-toolchain --hooks-json` path: rc=0, `hooks ->` deployed
  line + dormant line + `no .hook_state.json -> hooks sleep` clause present;
  no `.hook_state.json` anywhere in the ws.
- Acceptance checkbox "init 输出含 hook 激活语义说明(wired ≠ active)" → **PASS**
  (semantics unambiguous at both surfaces).

## Boundary / hygiene observations (no action required by injector)

1. **Transient first-run anomaly (NOT counted anywhere)**: the very first combined
   pytest run in this session showed both wiring tests RED with the exact pre-fix
   output signature while the tree was clean; 4 subsequent identical runs + all
   later runs green (root cause unproven; coincided with `uv run` first creating
   `.venv` at 13:28). It cannot be credited as a kill (no mutation present), and
   mutation b1 later reproduced the same red deterministically WITH the mutation
   in place — the net demonstrably catches the real defect.
2. `uv run --project .` dirties `uv.lock` on every sync — restored before handoff.
3. Minor echo: printing the em-dash dormant line to a GBK console raises
   UnicodeEncodeError (observed in my throwaway N2 driver, product subprocesses set
   PYTHONIOENCODING=utf-8 and are unaffected; output-hygiene already parked in the
   separate init-negotiation issue per RUNBOOK §3 — not #454 scope).

## Final state

- `git status --porcelain` → empty (clean; only this untracked `.review/FAULT-INJECT.md` remains, per dispatch instructions).
- HEAD unchanged at `bc0aa27`; no push, no remote, no other worktree touched.
- Post-restore verification: `pytest -q -m "not load_sensitive"
  tests/test_init_toolchain_gate.py tests/test_issue454_wiring_transparency.py`
  → **24 passed**.

## Verdict

**PASS** — kill-rate 6/7 (85.7%) ≥ 1/3; all 4 negative-case scenarios land on the
expected path; both issue acceptance checkboxes verified from the adversarial side.
The only survivor (c3 TTL→timeout) is a documented, intentional OR-escape pin
(RUNBOOK risk ②), not an empty net.
