# Design — issue 1005, C1 s2 (per-sample capability report)

## D1. Six faces, one document, each naming its organ

The report joins only organs that already exist; it computes no new quantity
and keeps no state:

| face | organ, in priority order | absent when |
|---|---|---|
| `facts` | `facts/_INDEX.md` through `update_index.count_by_status` (the sanctioned O(1) status organ), else `facts/*.md` frontmatter through `lint_facts.parse_frontmatter` | no `facts/` directory |
| `accuracy` | the eval row's `verdict` / `evidence_ref` / `metrics.converged`, judged by `eval_control_arm`'s predicates | the row carries no verdict |
| `ground_truth` | `eval_dataset.resolve_task_dir` + the unit's `ground_truth.json` **existence** | the unit is not in the corpus root |
| `tokens` | `session_cost.transcript_usage` (harvested at run), else one fresh fold of the session (`eval_loop_runner.transcript_usage`, the ② gauge) | no transcript for the workspace |
| `cockpit` | `runs/.cockpit-ratio.json` as the hook wrote it | the hook never sampled |
| `wall` | `loop.session.wall_s`, else `bench_tokens.collect(tx)["wall_s"]` | neither organ exists |
| `dispatch` | `loop.metrics.dispatch_count`, else `eval_loop_runner._factor_face` over the mission ledger | neither the row nor the ledger exists |
| `human` | `bench_tokens.collect(tx)["user_turn_count"]` + `bench_tokens.human_intervention` | no transcript |

Two of these deliberately report **two** numbers instead of one blended
value: `dispatch` also carries `dispatch_ledger_rows` and
`worker_transcripts`, and `facts` carries `files_seen` next to the index count.
Where the organs disagree, the disagreement is the finding.

## D2. An absent organ is never a zero

The eval runner's own harvest turns a missing `mission_ledger.yaml` into
`dispatch_count: 0` ("a missing organ is a zero metric" —
`eval_loop_runner.loop_metrics_from_ledger`). That is right for its purpose
and wrong for a capability report: it makes "we never looked" and "nothing was
dispatched" indistinguishable. Measured on the local corpus, a real workspace
(`ws-ccd-tf-snake-trainer-v1-20261028T131050Z-68767`) has **no** mission
ledger at all, and the same workspace's session has a worker transcript — so 0
would have been an outright false statement about a sample that dispatched
work. The report keeps the row's number when the row has one (the run-time
record is authoritative for what the run saw) and reports `None` + reason when
no organ exists.

## D3. Accuracy comes from the control arm, not from a second opinion

`eval_control_arm.py:30-46` defines the repo's five metrics (answer rate,
proven-with-evidence, premature closure, false proven, budget). The report
imports that module's answer set (`_ANSWER_VERDICTS`) and its four predicates
and rate functions rather than restating them, and the claimed-closure bit is
read where `arm_metrics` reads it: the **checker's** `row["metrics"]
["converged"] == 1`, not the loop's own `loop.metrics.converged` bool. Those
two disagree on real rows (measured: `eval-results-20261103T050859Z-38820.json`
has `metrics.converged: 0` and `loop.metrics.converged: false` side by side),
and picking the loop's bit would silently redefine the metric.

`test_batch_rates_equal_the_control_arm_on_the_same_rows` pins the whole
contract: the same three rows are graded by `arm_metrics` and by
`aggregate`, and all four rates must agree.

The two falsification legs (`minted_only_grade`, `rerun_verdict`) execute a
toolchain and can take minutes per sample, so they are opt-in. With no regrade
the legs stay `None` and both accusation predicates answer False — "reported,
never accused" is that module's own posture, quoted in its docstring.

## D4. Item ④ — the premise is stale, so no new runtime reader is built

The slice says: "the cockpit ratio's only reader is `heartbeat_tick.py:761`,
and L11 deletes it; find it an L11-era reader." Checked, not assumed:

1. `scripts/heartbeat_tick.py:761` is still that file's only reader
   (`grep -rn cockpit-ratio --include=*.py scripts/ hooks/ devkit/ tools/`).
2. The L11 branch (`feat/1001-monitor-removal-l11`, tip `84cd1e03`, last
   commit 2026-11-23T14:53Z) **does** delete it:
   `git diff --name-status dc7676ff feat/1001-monitor-removal-l11` shows
   `D scripts/heartbeat_tick.py` (873 lines) and
   `D scripts/heartbeat_loop_prompt.py`.
3. #1086 (opened 2026-11-25T04:03Z — after that snapshot) rules the opposite
   way for the same file: its target shape is
   `OS cron -> heartbeat_tick --wake-gate` with the gate host surviving and
   the cron demoted to a watchdog (#685 D5, "deletion explicitly out of
   scope"), and its own Out-of-scope section says "This card does not delete
   it". `git grep wake-gate` over the L11 tree returns **nothing**: the branch
   predates the ruling it must be rebased onto.
4. The S5 slice text already carries that correction (line 52: the acceptance
   line became "the cron is no longer the scheduler", and the registered cron
   runs `heartbeat_tick --wake-gate`).

So "L11 deletes the reader" is no longer a settled fact — the file is now the
pre-LLM gate's host, which S18 wires. Designing a replacement reader against a
deletion the newer ruling forbids would be speculative work on an unresolved
question, and would add a second reader with different semantics to a face
that has exactly one today.

What C1 does instead, and what is left to whom:

- ① makes the existing reader useful: `analysis_output_tokens` was 0 on every
  session, so the ratio was `machine/1` and unreadable wherever it was read.
- The per-sample capability report now carries the face, which is a consumer
  that does not depend on the tick process's fate (measured: the stored faces
  in the local corpus show `analysis_output_tokens: 0`, `worker_transcripts:
  null` — the pre-fix shape — so this consumer also makes the fix's effect
  visible per sample).
- S5's removal matrix — which its own slice says "has never been written" —
  must carry the row: `heartbeat_tick` → consumer `.cockpit-ratio.json` →
  replacement. That is the correct owner of ④, not a gauge slice. Reported in
  the s2 handoff for the closeout segment to file.

## D5. Finding — the `Z` in run-artefact names is local time

`eval_loop_runner.py:1175` and `:1281` build workspace and results-document
names with `time.strftime('%Y%m%dT%H%M%SZ')`, which formats **local** time
while labelling it UTC. Measured: the workspace
`ws-tf-snake-trainer-v1-20261028T131042Z-68731` holds the transcript of a
session whose last row was written `2026-10-28T06:39:44Z` with a 5400 s wall
cap — i.e. the run started 05:10Z, and the name's `131042Z` is 13:10 local
(UTC+8).

Consequence for this gauge: the name stamp cannot bound the transcript search.
Using it as UTC made every historical sample report "no transcript" (the
floor landed hours in the future). The report therefore searches with an open
window unless the caller supplies a real launch epoch, and reports
`candidates_in_dir` so a reused workspace directory stays visible rather than
silently yielding its newest session. The naming bug itself is out of scope:
renaming run artefacts would invalidate paths already recorded in existing
documents.

## D6. Corpus availability

`resolve_task_dir` reads `eval_dataset.eval_root()` (repo `eval/`, redirected
by the declared `KUNGLAO_EVAL_ROOT` switch). The historical blocked-path
smoke units those rows reference (`tf-snake-trainer-v1`,
`tf-novelvm-rust-v1`, …) are **not** in the current corpus, so their ground
truth is unresolvable and the report says so instead of inventing a grade; a
release-tier unit that does exist (`win-kdf-l1`) exercises the present path.
Any K1/K2 readout therefore runs with `KUNGLAO_EVAL_ROOT` pointed at the
corpus that produced the rows it reads.

## D7. Cost unit: tokens are the denominator, dollars a covered subset

Owner ruling on this slice: the cross-arm comparison denominator is
`bench_tokens.grand_total` — the unit the repo already declared
(`scripts/bench_tokens.py:10`: "all four summed (the experiment's cost unit)",
computed at `:94-95`). It exists on every session including the hard-killed
ones and carries zero pricing assumption. Dollars stay secondary: present only
where the CLI itself reported them, attached to their coverage share, and never
interpolated. Item (b) of the choice — a `cost_source`-tagged rate table — was
rejected because the tag labels a bias, it does not remove it: the killed
sessions would still sit on a different money scale than the completed sessions
they are compared against.

**One correction the ruling needs in implementation.** `bench_tokens.collect()`
takes ONE transcript path, so its `grand_total` sees only the orchestrator rows
— worker spend lives in the sibling files this issue's first half made readable.

Measured on four real sessions (s1 proposed the check, s2 re-ran it
independently; `bench_tokens.collect()` equalled the orchestrator population in
**4/4** cases, so the single-file face is exactly one population):

| session | worker transcripts | single-file unit | session denominator | undercount |
|---|---|---|---|---|
| `e67cafdc` | 1 | 14,900,406 | 15,519,178 | 4.0% |
| `c4b36686` | 1 | 203,904 | 220,672 | 7.6% |
| `a9e7e5ca` | 39 | 1,837,410,746 | 4,168,350,569 | 55.9% |
| `144ca112` | 307 | 7,183,866,178 | 12,220,662,382 | 41.2% |

What the table does and does not say. The undercount is by definition
`(session − single-file) / session`, and since the single-file face equals the
orchestrator population (verified 4/4 above), that difference IS the worker
share of session spend — an identity, not a finding. So the table supports one
empirical claim only: **the share is not a small constant** — measured from
4.0% up to 55.9% of session spend across four sessions. Its ceiling is
definitional, not empirical: `worker / (orchestrator + worker)` is bounded by
100%, attained only when the orchestrator population has no usage rows at all.
What the measurements rule out is a fixed correction factor, not a bound. It refutes the tempting generalisation:
the undercount is **not predictable from the worker-file count** — 307 files undercount
41.2%, LESS than 39 files at 55.9% — so any estimate of a session's cost from
dispatch counts is wrong in both directions.

What the denominator choice does turn on is WHICH population is dropped. It is
the worker population, and the treatment K1/K2 test is precisely whether a
learning arm dispatches workers, so a single-file denominator makes the arm that
dispatches more look cheaper. That is a bias in favour of the thing under test,
not a precision loss, and it holds without any monotonicity assumption.

Two normative rules follow, and only these two are pinned in the spec:

1. with worker transcripts present, the three totals (orchestrator, worker,
   session) are reported and the denominator is `tokens.grand_total.session` —
   never `bench_tokens.collect()` on the main transcript;
2. with no worker transcripts the report equals `bench_tokens.collect()` on the
   same transcript (`test_grand_total_matches_the_bench_meter_without_workers`),
   so the two faces are interchangeable in the degenerate case and cannot
   silently disagree in the real one.
