## Why

A workspace record can name a checker without establishing who produced it. Downstream use credit needs the identity reported by the host for the independent checker execution.

## What Changes

- Sign successful checker returns for downstream use with the existing learning seal, binding the result to its workspace and host call.
- Require that evidence for deliverable use credit when the learning seal is armed.
- Keep unsigned references auditable and preserve existing unarmed replay behavior.

## Capabilities

### New Capabilities

- `deliverable-checker-attribution`: Host attribution for downstream use records.

### Modified Capabilities

None.

## Impact

The existing Agent completion hook, downstream use record reader, and delivery instructions. Claim verification and settlement verdict writers are outside this change.
