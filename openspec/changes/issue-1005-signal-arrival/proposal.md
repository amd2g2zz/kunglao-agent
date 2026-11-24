## Why

Issue #1005's audit read the learning loop as "acts but never closes" off a
workspace whose files did not all exist: "no settlement" was read where
nothing had been recorded, and the unmatched settlement result leaves no
ledger row at all. Before N1–N3 change the design, the chain needs one
instrument that counts, from what is durably on disk, how far a signal
travelled in a workspace — candidates, staged dispatch decisions, ledger
rows, settlement, credit, posterior — and says `no data` with the reason
where a source is missing, instead of printing 0.

## What Changes

- Add `scripts/rlvr/signal_arrival.py <workspace>`: a read-only report
  (schema `signal-arrival/1`) with seven counts, each a number or an
  explicit `no data` that names its source.
- Keep 0 and `no data` apart everywhere: 0 is a fact about a source that
  exists.
- Count the unmatched settlement result where its trace stays: the warn
  rows of `q_cells.observe_settlement` in the run log. `settlement.attempts`
  counts the results of that call which left a trace: the rows it banked
  plus those warn rows. Credit rows of other faces (step banks, calibration
  banks, amendments) are not settlement attempts and are counted apart. The
  deferred credit files of the blind path are counted apart too: each is
  deleted once its credit is banked, so they are what is still waiting, not
  a lasting trace.
- Make the report read-only by construction: the standard library only, no
  ledger read face of the repository, nothing opened for writing.
- Register the script: a `scripts/README.md` row, the package facade line
  `tests/test_rlvr_facade_756.py` requires, and the deployment manifest.

## Capabilities

### New Capabilities

- `signal-arrival-report`: the read-only seven-count report over a
  workspace.

### Modified Capabilities

None.

## Impact

One new module under `scripts/rlvr/`, one import line in
`scripts/rlvr/__init__.py` (the facade contract), the script inventory and
the deployment manifest. No hook, ledger, learner or decision path changes:
the report reads files and writes nothing. The two real workspaces named
in the pipeline notes are read, never written; their reports stay local
under the relay's evidence directory.

Not in this change: the paid half of slice N0 (two real sessions at the
pinned tip), which waits for the model channel.
