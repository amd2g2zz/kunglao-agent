# probe-tiers spec delta — #474

## ADDED Requirements

### Requirement: toolchain checks SHALL carry an explicit probe tier (presence/liveness/capability)

Every `CheckResult` produced by `scripts/toolchain.py` SHALL carry a `probe` field classifying HOW it was verified: `PRESENCE` (file/registry lookup), `LIVENESS` (side-effect-free network handshake — TCP connect, adb forward + recv, raw JDWP handshake), or `CAPABILITY` (real trial run of the tool). The JSON output SHALL include the tier per check item. Existing checks SHALL be classified truthfully: `pefile import` / `gitnexus --version` / `adb shell su -c id` / `getprop` read-backs are CAPABILITY; forward-probes, VM TCP connects, and the jdwp handshake are LIVENESS; `shutil.which` and file-exists checks are PRESENCE.

#### Scenario: JSON exposes the probe tier

- **GIVEN** any toolchain report
- **WHEN** formatted as JSON
- **THEN** every check item contains a `probe` key whose value is one of `presence`, `liveness`, `capability`

### Requirement: the decompiler check SHALL report three honest states, never a fake PASS

A registered `ghidra`/`ida-pro-vm` MCP name plus a reachable bridge port, or a present CLI binary, SHALL yield status WARN (HARD tier) with a detail naming exactly what was verified and stating that decompilation capability is unverified — because a Python probe cannot reach into the MCP session (tools register only after `connect_instance`). Status PASS SHALL require a CAPABILITY trial (`analyzeHeadless` importing a minimal synthetic ELF successfully) and SHALL only run when capability probing is explicitly requested (`check(..., caps=True)` / CLI `--capability`). Complete absence SHALL remain FAIL (android pure-DEX keeps its existing WARN nuance).

#### Scenario: registered MCP is WARN, not PASS

- **GIVEN** a registry with `ghidra` registered and the bridge port accepting TCP
- **WHEN** the decompiler check runs on the default path (no caps)
- **THEN** the item status is WARN with probe tier LIVENESS and the detail contains "capability unverified" — it is NOT PASS

#### Scenario: capability trial PASS only under opt-in

- **GIVEN** GHIDRA_HOME with an analyzeHeadless that successfully imports the synthetic ELF
- **WHEN** `check(ws, t, caps=True)` runs
- **THEN** the ghidra item is PASS with probe tier CAPABILITY and the trial detail

### Requirement: the android manifest SHALL include a jdwp liveness handshake probe

A `jdwp_debug` check SHALL exist in the android check set: discover debuggable pids via `adb jdwp`, `adb forward tcp:<local> jdwp:<pid>`, then perform the raw JDWP handshake — send the 14-byte ASCII `JDWP-Handshake` and require the same 14 bytes echoed within a short timeout. It SHALL NOT use `jdb -attach` (attach has side effects on the target). With ADB unavailable, or on a handshake echo mismatch/timeout, the check SHALL report WARN (capability-absence, tier WARN — never blocking). *(Amended 2026-08-19 per user ruling: jdwp is NOT a hard requirement — static-only and frida-driven flows never touch jdb; the miss is surfaced to the orchestrator, which decides per-task whether to repair. Original SHALL text: cascade-FAIL/FAIL — superseded.)* The android matrix documentation SHALL mention jdb as the interactive driver (fallback), and the JDWP probe as the mechanical gate.

#### Scenario: handshake echo PASSes

- **GIVEN** a fake JDWP server echoing the 14 handshake bytes and a fake adb wiring forward
- **WHEN** the android check runs
- **THEN** `jdwp_debug` is PASS with probe tier LIVENESS and the detail names the pid

#### Scenario: wrong echo FAILs

- **GIVEN** a server that accepts the handshake bytes but echoes different data
- **WHEN** the android check runs
- **THEN** `jdwp_debug` is FAIL (not a crash) with fix guidance

### Requirement: capability probes SHALL run only under explicit opt-in

`check(ws, type)` on the default path SHALL execute presence and liveness probes only. CAPABILITY trial runs (decompiler import, and any future capability probe) SHALL be gated behind the `caps=True` parameter / `--capability` CLI flag and SHALL NOT be invoked by the periodic or default init path. Init's call orchestration is out of scope (#478).

#### Scenario: default path never trials capability

- **GIVEN** the capability seam is instrumented to count calls
- **WHEN** `check(ws, "android")` runs without caps
- **THEN** the count is 0
