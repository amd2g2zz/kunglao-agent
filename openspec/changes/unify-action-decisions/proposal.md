## Why

The dispatch gate can adopt a sampled method that disappears when the recorder rereads the request. The executor and hook also reconstruct competing views of a decision. See #1064 and #1061.

## What Changes

- Carry the actual method and its source to the existing dispatch observation and settlement join.
- Compute recommendation and attribution once per dispatch on both entry paths.
- Reconcile superseded specifications, documentation and helpers with the shared contract.

## Capabilities

### New Capabilities

- `dispatch-attribution`: Preserve method attribution across dispatch and independent settlement.

## Impact

The dispatch hook, evaluation executor, strategy store and Q-cell ledger read/write path. Existing candidate ranking and settlement rules remain authoritative.
