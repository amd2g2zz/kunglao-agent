## Why

The Stop hook can accept completion without invoking the existing mission settlement, leaving the episode pool and its derived views disconnected from production. INV-003 requires family-level posterior movement and INV-005 requires settlement credit; neither may be inferred from a hook exit code alone.

## What Changes

- Connect proven mission-terminal Stop events to the existing settlement, with replayable, recoverable accounting.
- Bind successful and independently verified failed outcomes to genuine checker evidence, distinguish them from interruption and unverified surrender, and prevent duplicate or fabricated episodes.
- Record useful, privacy-preserving face spans and exercise the real dispatch, checker, settlement, credit and posterior path with synthetic data.
- Add a development-only, reproducible within-task comparison with explicit unsupported interventions and limitations.
- Keep strategic declaration S5 view-only as a proposed decision, pending the owner's ruling. Its historical smoothed frequency is not a behavioral selection probability.

## Capabilities

### New Capabilities

- `production-terminal-settlement`: durable, evidence-bound settlement and observability at the real Stop boundary.
- `within-task-evaluation`: reproducible development-only paired mock comparisons and ablations.

### Modified Capabilities

None.

## Impact

The Stop hook, mission settlement and recovery consumers, face telemetry, synthetic integration tests and development-only evaluation are affected. Prior slices remain authoritative and S5's acceptance stays open until the owner decides.
