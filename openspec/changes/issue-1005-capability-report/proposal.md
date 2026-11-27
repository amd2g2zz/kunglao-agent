# issue 1005 — C1 capability report (s2: per-sample capability faces)

## Why

Nothing in the repo answers "what did this sample cost and what did it get"
in one place. The six numbers the capability question needs are all recorded
somewhere, but in six organs nobody joins:

| face | where it lives today | who reads it |
|---|---|---|
| outcome grade | the eval row's `verdict` / `evidence_ref` / `metrics.converged` | the results doc and the control arm's batch metrics |
| facts by status | `facts/_INDEX.md`, else `facts/*.md` frontmatter | `update_index.count_by_status`, the linter |
| orchestrator vs worker tokens | the session transcript's usage rows (split by the same issue's ② gauge) | `eval_loop_runner.transcript_usage` |
| wall clock | `loop.session.wall_s`, else the transcript's timestamp span | the results doc |
| dispatch count | `loop.metrics.dispatch_count`, else `runs/mission_ledger.yaml` dispatch events | the eval runner |
| human interventions | genuine user turns in the transcript | `bench_tokens.collect` |

So a per-sample capability question gets answered by hand, ad hoc, with each
reader free to invent its own meaning — and the failure mode is not a missing
number but a **zero that is really an unread organ** (measured on the local
corpus: a workspace with no `mission_ledger.yaml` yields `dispatch_count=0`,
and 15 of the 30 real session rows have no cost face at all).

## What Changes

- New gauge `scripts/capability_report.py`: one JSON capability report per
  eval sample, plus a batch summary. It reads an eval-results document
  (`--results`) or one workspace (`--workspace`), joins the six faces above,
  and writes `<out>/capability-<unit>.json` + `summary.json`. Default `--out`
  is `<repo>/experiments/capability-reports/<utc-ts>/` — the gitignored local
  run tree; a report is a run artifact, never a repo asset.
- **Provenance on every face.** Each face carries `source` naming the organ it
  read. Where no organ exists the face reports `None` plus a `reason`, and an
  unread organ is never laundered into a zero: `dispatch_count` distinguishes
  "the ledger said 0" from "there is no ledger", the token account says
  "absent", and a row without a verdict reports `correct: null`, not FAIL.
- **Accuracy reuses `scripts/eval_control_arm.py`'s definitions** (its
  five-metric block) instead of restating them: `answered` comes from that
  module's answer set, `proven_with_evidence` from PASS-plus-evidence,
  `false_proven` / `premature_closure` from `is_false_proven` /
  `is_premature_closure`, and the batch rates from `answer_rate` /
  `proven_with_evidence_rate` / `premature_closure_rate` /
  `false_proven_rate`. `aggregate` therefore cannot drift from the control
  arm's readout (pinned by a test that runs both on the same rows).
- **The two falsification legs are opt-in** (`--regrade`): the minted-probe
  subset and the fresh checker re-run execute a toolchain, so by default the
  report states the run-time grade and says the legs were not run — an
  ungraded candidate is never accused (the arm's own posture).
- **No corpus content travels.** The ground-truth face names the unit and its
  `ground_truth.json` path and says whether the file exists; it never copies a
  constant out of it (owner rule: the eval corpus is intermediate material).
- **Cost faces follow the owner's ruling on this slice**: the cross-arm denominator
  is `bench_tokens.grand_total` (the unit the repo already declares at
  `scripts/bench_tokens.py:10`), summed per population and then added — because
  `bench_tokens.collect()` reads one file and would drop the worker part
  (measured: 1,605,184 of a 10,760,827-token session, 14.9%). Dollars stay a
  secondary face with their coverage share, never interpolated.
- The report also carries the workspace's `runs/.cockpit-ratio.json` face as
  written, so the harness-vs-analysis ratio the ① gauge fixed has a consumer
  that does not depend on the tick process's fate.
- NOT done — a second *runtime* reader for the cockpit ratio (slice item ④).
  Its premise ("L11 deletes `heartbeat_tick`") is stale: #1086 (opened
  2026-11-25, two days after the L11 branch's last commit) makes
  `heartbeat_tick --wake-gate` the registered cron command, and the S5 slice
  already carries that correction. Evidence in `design.md` D4.

## Impact

- One new script, one new test module, three registrations
  (`scripts/README.md`, `deploy-manifest.yaml`, `tests/_tiers.py`).
- No behaviour change: the gauge reads workspace and transcript files and
  writes only under `--out`. No decision, dispatch, settlement or wake path
  consumes it yet — the K1/K2 campaign readout is its intended first reader.
- Incidental finding, not fixed here (design.md D5): the workspace and
  results-document name stamps are local time labelled `Z`
  (`eval_loop_runner.py:1175,1281`). The report therefore does not use them as
  a launch bound.

Refs #1005 (not Closes).
