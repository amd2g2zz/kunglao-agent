## Why

Certified fact fixtures use a fixed review date and become stale as time passes, causing unrelated tests to fail.

## What Changes

- Generate fixture creation and review dates from the current local date.
- Exercise freshness across dates and preserve the real linter's stale warning.

## Capabilities

### New Capabilities
- `fact-fixture-freshness`: Certified test facts remain fresh when generated.

### Modified Capabilities

## Impact

Only shared test fixture generation and its tests change; production lint rules remain unchanged.
