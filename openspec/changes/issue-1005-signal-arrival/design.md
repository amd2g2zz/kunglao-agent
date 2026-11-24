# Design

## Context

Slice N0 (issue #1005) needs an instrument that counts the learning chain
on a real workspace before N1–N3 change it. The pipeline notes name three
existing read faces to reuse "only after confirming from their code that
they do not write": `consolidated_ledger.read`, `liveness` and
`scripts/posteriors_case.py`.

## Goals / Non-Goals

Goals: seven counts that are right about what is on disk, a report that
cannot write into the workspace it reads, and no blank anywhere.

Non-Goals: computing the q-cell fold's per-family posterior; judging the
numbers; changing any writer.

## Decisions

### 1. The report imports the standard library only

The three named read faces were read before any reuse:

- `consolidated_ledger.read` (scripts/rlvr/consolidated_ledger.py:353-374)
  and `liveness` (:377-392) read only on the happy path, but an unreadable
  file or a refused store override calls `kunglao_log.warn`, whose ledger
  face appends an `action=warn` row to the run log of whatever workspace
  it finds — the pinned one, else the nearest directory above the cwd that
  holds `task_spec.yaml` or `runs/` — and then prunes day files
  (scripts/kunglao_log.py:138-182, 761-905, 1011-1023).
- `PosteriorLedger.load` (scripts/posteriors_case.py:245-274) warns the
  same way when a seal does not verify.
- `strategy_store._support_material_present` writes a marker file outright
  (scripts/rlvr/strategy_store.py:551-562), and `learning_seal.trusted_rows`
  documents that it takes "one small workspace write on the read path"
  (scripts/rlvr/learning_seal.py:393-420).

So no repository read face is reused. The module parses the same files
with `json` and `os.scandir`; `tests/test_signal_arrival_1005.py` pins,
in two tests, that the report's ledger counts equal
`consolidated_ledger.liveness` and `q_cells.dispatch_rows` on one
workspace, so a layout move cannot make the two readers disagree silently.
A structural test pins the import surface itself, because the behavioral
read-only test cannot reach every degraded path (a file made unreadable by
its permission bits depends on the user running the tests; a directory in
place of a file, or the reverse, raises the same `OSError` without
privileges and is tested).

### 2. 0 and `no data` are different facts

A source that is missing, empty or unparsable gives `no data` plus the
reason; a source that exists and holds nothing of a kind gives 0. The
#1005 audit's error was reading absence as a count. A line the decoder
cannot finish — valid JSON nested deeper than it can go — is `unparsable`
like a line that is not JSON: the decoder gives up with `RecursionError`,
which is not a `ValueError`, so both are caught at the two `json.loads`
sites.

### 3. Leaf contract

Every count is a dict of leaves. A leaf is `{"value": <number | mapping>,
...}` or `{"value": "no data", "reason": "..."}`; `reason` is present
only with `no data`. Empty lists are omitted by `_prune`, so nothing under
`counts` is null, an empty string or an empty list. The `workspace_build`
block uses the same leaf shape: the value, or `no data` with the reason
beside it.

### 4. Where each count comes from, and what is not durable

| Count | Source | Not durable / limit |
|---|---|---|
| 1 candidates | `candidates` column of the first `q-cell-obs/1` dispatch row (scripts/rlvr/q_cells.py:1219-1232); else the earliest `<dispatch_id>-<tool_call_key>.json` in `runs/.dispatch-decisions` (hooks/worker_budget_sinks.py:726-756); `runs/llm-prior.json` with the tolerance of `priors.read_intake_prior` | a row written before the `candidates` column has no receipt: `no data` |
| 2 dispatch decisions | `runs/.dispatch-decisions`, the dispatch rows of `runs/experience.jsonl`, `runs/dispatch-ledger.jsonl`; the join compares an id as a string on both sides | a receipt is deleted once execution is proven (hooks/worker_budget_sinks.py:789-791): the directory counts receipts still waiting, not receipts ever staged |
| 3 settlement | `attempts` = `banked` + `unmatched`. `banked`: the `q-cell-obs/1` rows with `source` `settlement`, a numeric credit and no step kind — what `q_cells.observe_settlement` appends when a pending dispatch row matched (scripts/rlvr/q_cells.py:1781-1795). `unmatched`: the warn rows of that call in `runs/logs/kunglao-*.jsonl`. `other_credit_rows`: the credit rows of the other faces, by `credit_kind` (`step`, `step_calibration`) or `source` (`credit-amendment`) | the unmatched result appends no ledger row (scripts/rlvr/q_cells.py:1774-1780); the trace that stays is the run-log warn row — at most one per process and dispatch id, and only while its day file is among the newest 30 the log keeps, whatever their dates (scripts/kunglao_log.py:981-1008). `attempts` is neither a bound nor every call: a repeat in one process warns once, a swept day file takes its warn rows, a bank whose row the ledger refused is in no count, and a step bank written without its `credit_kind` column reads as `banked` (in this repository every step and calibration row has carried the column since the faces exist). The blind path's deferred credit file (scripts/rlvr/settlement_wire.py:591-614) is deleted once the credit is banked (`:636`): `deferred_credit_files` counts what is still waiting |
| 4 credit rows | every `q-cell-obs/1` row with `source` in {settlement, credit-amendment} and a numeric credit: `booked` = `settlement.banked` + `settlement.other_credit_rows` | the key is the row's `dispatch_id`, else its `claim` (older builds wrote none) |
| 5 posterior | `runs/plan-receipts.jsonl` cells (the shape of `policy_state.posterior_summary`, scripts/policy_state.py:104-123); else `runs/policy-state.json` | `after` is the cell recorded at the last decision; credit banked after it is in no cell. The q-cell fold is not computed: its reader writes when the seal is armed |
| 6 hypothesis-resolution | `hypothesis-resolution/1` rows of `runs/experience.jsonl` | none |
| 7 method lead | the `dispatch-lead` section of `runs/round-strategy.json` | the seam has no `method_lead` field: `compose._seam_sections` renders the lead as a sentence (scripts/rlvr/compose.py:943-950); the structured field is in `runs/round-strategy/tick-*.yaml`, which this report does not parse |

### 5. The dispatch-id join is reported

The #1005 problem statement names two ledgers carrying different ids for
one dispatch as the reason settlements come back unmatched. The report
counts the ledger dispatch rows whose `dispatch_id` the dispatch ledger
also carries, and the rows that carry no id. Both shapes exist on disk: a
workspace where the q-cell row and the dispatch ledger hold two different
ids for one dispatch, and one whose dispatch rows carry no id at all; the
pipeline's evidence directory holds the two reports (they stay out of the
repository).

### 6. Entry, exit codes, output

`main(argv)` follows the house `main(argv=None) -> int` shape. A path that
is not a directory is a usage error: exit 64 and nothing on stdout, the
same code `scripts/kunglao_log.py` uses for a missing workspace — a typo'd
path printed as "every count: no data" would read as an empty workspace.
The JSON is ASCII-only (`ensure_ascii` default), so the entry carries no
stdio reconfiguration and needs nothing from `scripts/` at run time.

### 7. Registration consequences

`tests/test_rlvr_facade_756.py` requires one `from . import <name>` line
per file under `scripts/rlvr/`, so `scripts/rlvr/__init__.py` gains
`from . import signal_arrival` and every `import rlvr` now imports the
module: it must stay free of import-time side effects (it is — stdlib
only, no I/O at import). `signal_arrival` is not added to `__all__`
because nothing outside the package imports it. The import closure puts
the module into `deploy-manifest.yaml`.

## Risks / Trade-offs

- Parsing the files a second time instead of calling the canonical readers
  can drift when a layout changes; the two agreement tests limit that to
  one workspace shape.
- `attempts` adds ledger rows to warn rows, two traces with different
  limits; the report shows both components, so a reader never has to trust
  the sum alone.
- A credit row is attributed to a face by its own columns (`source`,
  `credit_kind`), not by a record of the call: a build that wrote a step
  bank without the kind column would read as a settlement bank.

## Migration Plan

None: additive. No writer changes and no workspace is migrated.
