# issue-1037-heartbeat-test-clock

## Why
The durable heartbeat tests capture `datetime.now(timezone.utc)` at module import. A long pytest collection or earlier suite can make that fixture older than the heartbeat threshold before this file executes, producing false stale results.

## What Changes
Construct one UTC reference timestamp per test at execution time and use it for all synthetic recent/expired records. Add a regression test that simulates collection-to-execution delay and preserves real threshold positive/negative heartbeat assertions. Production heartbeat code is unchanged.

## Invariants
Heartbeat verdicts continue to use the real implementation and its configured age threshold; only test fixture clock construction changes.

## Integration contract
`tests/test_heartbeat_durable_830.py` remains compatible with pytest collection and existing heartbeat APIs. No production files, public APIs, or release assets change.
