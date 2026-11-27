## Why

A previously executed tool test leaves a logging workspace pinned. The learning-seal test fixture resets per-process flags but retains that workspace, letting a prior test's persisted once-marker suppress the next test's warning.

## What Changes

- Give each test using the seal key fixture a fresh warning workspace and restore the previous process state after the test.
- Preserve the actual logging and learning-seal behavior, including the explicit workspace once-marker tests.

## Capabilities

### New Capabilities

- `seal-test-isolation`: independent warning workspace for learning-seal tests.

### Modified Capabilities

None.

## Impact

Only test fixture state; no production behavior or deployed files change.
