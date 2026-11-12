# Design

A pytest fixture yields a single `datetime.now(timezone.utc)` when each test starts. Helpers accept that timestamp explicitly, so every record in a test shares one execution-time clock. A subprocess plugin supplies a controlled datetime only to the target test module before import, then advances its shared clock 61 minutes after collection and supplies that same clock to `rlvr.liveness`, where the real evaluator reads time. Recent and expired records are evaluated without replacing heartbeat logic; the subprocess has a 120-second timeout.

## Integration contract

Caller: pytest invokes the per-test fixture and the regression subprocess. Trigger: each test execution after collection. Fingerprint: a 61-minute collection offset yields alive for recent records and stale for expired records using the production evaluator.


## Invariant coverage and retirement

The current invariant registry contains no applicable long-term heartbeat invariant. Single-change spec coverage therefore fails until the coverage policy or registry provides an applicable invariant. Issue #1001 plans to retire heartbeat continuity and the worker-budget heartbeat gate, replacing them with session liveness, an armed next wake, and no overdue deadline; that work must retire or replace this test contract when its consumers are removed.
