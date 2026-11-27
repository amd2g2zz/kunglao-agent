## Why

Issue #1042 has two remaining v0.1.6 defects. A writer can replace another process's successful case or question update using an older snapshot. Historical derived rows with a matching short claim ID can be revoked without evidence of their originating workspace.

## What Changes

Serialize production read/modify/write operations on the workspace posterior and consult durable committed case amendments before revocation. Bind new attributed method negatives to their workspace. Report unavailable historical ownership and retain the affected bytes. Recovery of an amendment whose posterior save failed remains tracked in #1059.

## Capabilities

### New Capabilities

- `case-amendment-isolation`: concurrent posterior updates and attributed revocation.

## Impact

Affects case reconciliation, oracle and question writers, and the derived knowledge discovery/revocation path. Existing posterior and ledger schemas remain readable.
