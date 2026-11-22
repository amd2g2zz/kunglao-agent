## Decisions

Use one per-workspace OS file lock across each posterior writer's read-modify-save interval. Acquire it before reading pair outcomes in the amendment path. Advisory locking shares the platform matrix's Windows and POSIX primitives; require a real lock. Incomplete or unreadable snapshots refuse every update before appending or revoking. Knowledge appends and revocations share a strict platform lock, with a distinct lock per workspace file. Discovery distinguishes missing paths from failed reads so a later reconciliation can retry. Readers can consume the existing atomically replaced snapshot without acquiring the lock. Acquisition order is posterior, experience/knowledge. No shared global lock or new journal.

The identity for claim-scoped derived rows is (workspace_id, claim). Match only supported negative and broadcast records, never the credit series. New attributed negatives carry the existing resolved workspace identity. A match without the historical workspace binding is unavailable. Discovery and deletion use the same classification. A failed append cannot authorize deletion. Pre-move files remain discoverable through the existing registry.

## Verification

Interleave real reconciliation with a separate question writer and verify both persisted effects. Exercise missing ownership alongside a known attributed record and an unrelated record. Reconcile twice, including after reopening the workspace. Keep refusal, revocation retry and sealed snapshot coverage. The committed-append/failed-save repair is explicitly separate.
