## Why

The Android debug flag CLI tests depend on host decompiler discovery because their former global MCP configuration is no longer read. On macOS the cumulative probes can exceed their 60-second subprocess timeout.

## What Changes

Declare a fixture MCP registration in the supported workspace configuration, and verify the actual CLI reports its unverified supply and still checks the Android debug flag. Product probes and timeouts are unchanged.

## Capabilities

### New Capabilities
- `debug-flag-tests`: isolate unrelated decompiler discovery in Android debug flag CLI tests.

### Modified Capabilities

None.

## Impact

Test fixtures and specifications only. This does not establish that a real MCP server or decompiler is available.
