# reject-telemetry-683 delta — issue-683-substrate-wiring

## ADDED Requirements

### Requirement: worker_budget gate REJECTs land in the gate-telemetry ledger

Every `worker_budget` gate REJECT SHALL append exactly one row to
`runs/gate-telemetry.jsonl` at the `_reject` chokepoint, carrying the
producer-qualified gate name (`worker_budget.<gate>`), the exit code the
emission site returns (2), the shared `rc_meaning` vocabulary, the
rejection reason (`msg`, truncated), and a timestamp. The REJECT's own
semantics — stderr summary, stdout guidance JSON, exit 2, the #55
verdict tag — SHALL NOT change.

#### Scenario: a tier-gate REJECT is auditable after the fact

- **WHEN** the tier gate rejects a dispatch in a workspace with a
  `runs/` directory
- **THEN** `runs/gate-telemetry.jsonl` gains one row whose gate is
  `worker_budget.tier`, whose rc is 2, and whose message carries the
  rejection reason — and the hook still exits 2 with the same guidance

#### Scenario: every battery gate rides the same chokepoint

- **WHEN** any `pre_check` battery gate (cap, heartbeat, workers,
  snapshot, methodfamily, ...) rejects
- **THEN** the row lands under `worker_budget.<gate>` in the same
  ledger, without per-gate wiring

### Requirement: Reject telemetry is fail-open bookkeeping

Telemetry SHALL never change a verdict: without a `runs/` directory, or
without a workspace key, or when the ledger append fails, or when the
telemetry module is absent from a partial deployment, `_reject` SHALL
still print its faces and return 2 — degrading at most to one
rate-limited `warn("reject_telemetry", reason)`.

#### Scenario: an uninstrumented workspace keeps the identical verdict

- **WHEN** a gate rejects in a workspace with no `runs/` directory (or
  a paths dict with no workspace key)
- **THEN** `_reject` returns 2, emits the same stderr/stdout faces, and
  writes no row — no exception surfaces

#### Scenario: a broken ledger append never blocks enforcement

- **WHEN** appending the telemetry row raises
- **THEN** the exception is caught, one `warn` names the operation and
  reason, and the REJECT still returns 2
