## ADDED Requirements

### Requirement: Android debug flag tests isolate decompiler discovery
The Android debug flag CLI test workspace SHALL declare a Ghidra MCP registration in its workspace configuration, so the CLI reports the registered supply as unverified without scanning the host for local decompilers.

#### Scenario: Registered fixture avoids local discovery
- **WHEN** the real Android toolchain CLI runs against the fixture workspace with a fake ADB reporting `ro.debuggable=0`
- **THEN** it reports the debug flag as FAIL, reports the Ghidra MCP supply as unverified, and does not invoke `mdfind`

#### Scenario: Debug flag policy remains exercised
- **WHEN** the CLI reads an opt-out with `ro.debuggable=0`, an opt-out with `ro.debuggable=1`, or no task specification with `ro.debuggable=0`
- **THEN** it reports WARN, PASS, and HARD FAIL respectively.
