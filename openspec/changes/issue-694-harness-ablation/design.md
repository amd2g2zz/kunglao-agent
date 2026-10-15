# design — issue-694-harness-ablation

The protocol file under `experiments/exp-s11-h-ablation/` (local-only,
gitignored) is the pre-registration; this document is its reviewable
design copy. Both are written BEFORE the first run; any amendment before
the run is recorded, never silent, and after the first run the protocol
is never edited — deviations are reported as deviations.

## The three arms

| Arm | Face | Realization |
|---|---|---|
| H0 | bare Claude Code | the registry's `cc-bare` (runner_face `cc-default`, store `none`, plugin-less session) — NOT a new arm; reused verbatim from `docs/design/ws5-five-arms.yaml` |
| H1 | slim harness, RL decisions off | `loop` face against the pinned slim snapshot (the five-face keep list only, decision-for-policy items demoted per the table below); every learned decision input starved (uniform family choice, no posterior-driven rank) |
| H2 | H1 + the listed decision set handed to the RL | same slim snapshot; the demoted decisions now come from the RL layer (sampler as the family exit with a logged propensity; posterior-driven rank; capability-switch as a decision with a recorded reason) |

All arms share: the frozen model alias, the same tool supply and MCP
faces, the same per-run budget caps, the same independent checker, and
the same task-family sequence. H1/H2 differ ONLY in who decides; H0/H1
differs ONLY in harness-vs-bare. The slim snapshot is pinned by tree
hash in the protocol; it is operator-local (never committed) — the
slimming list lands in the repo only if H1 > H0.

## The five-face keep/cut criterion (applied per item)

Criterion — an item is KEPT iff it serves one of the five faces; an
item that *decides for the policy* becomes advisory or is removed.

Kept faces (the boundary):
1. reward integrity — blind verification, certified facts, oracle;
2. termination and budget — ACT BUDGET, wall caps, worker budget;
3. evidence/execution classes — write-gate, sandbox boundaries;
4. observation/telemetry — step ledger, transitions, progress spine;
5. execution surface — tools, MCP, permissions.

Per-item table (the slimming list; anchors verified at protocol time):

| item | current behavior | face test | verdict |
|---|---|---|---|
| rank top-1 enforcement (`_top1_enforcement`, `hooks/dispatch_gate.py`) | REJECTs a rank>=2 dispatch unless the prompt carries an `agent-reasoning:` prefix | none — it decides claim order FOR the policy | DEMOTE to advisory rank: the rank is recorded, never blocks; the bypass prefix is deleted (an advisory needs no bypass) |
| capability-switch lock (`capability_switch_violation`, `scripts/priority_ratio.py`) | a validated capability can lock tool-family switches once `obstacle_for` cards arm (dormant today) | none — it decides method family for the policy | DEMOTE to a decision with a recorded reason |
| `try_alternate_method` bans (`scripts/error_response.py`, three error classes) | forbids choosing an alternate method in HUMAN_EVENT_REFUSE / CONFIG_CHANGE_REQUIRED / UNCLASSIFIED | none as a blanket ban — a specific class may still guard a kept face | RESCOPE: allowed as a decision, recorded; the ban survives only where a kept face needs it |
| `CATEGORY_OPERATOR_ACTIONS` (`scripts/action_space.py`) | hand-written claim-category -> operator map; no production consumer | none (dead decision surface) | REMOVE, or wire it as an advisory input only |
| reference recall injection (`hooks/recall_inject.py`) | context injection on by default (measured H2H: zero improvement, +46% cost; 19 injections covering 144 files in one live workspace) | observation — but measured zero-value | DEFAULT-OFF (`KUNGLAO_RECALL=0` at the matrix face); stays a face, stays switchable |

Deferred (re-triage AFTER the H0/H1 read, per the card): the scheduling
cron (`#685`), the liveness triad (`#682`, closed), and the
scheduled_tasks schema handling (`#679`, closed) — slimming candidates
whose verdicts wait on the ablation numbers.

## Metrics, sequence, stop rule (fixed in the protocol)

- Units: the six release-tier interpolation-holdout units of the
  registry (web-token-v1, web-pow-lite-v1, apk-static-license-v1,
  rust-apk-beacon-v1, web-anticrawl-v2, apk-webview-attest-v2); the
  operator-corpus extrapolation units ride only if the owner arms them.
  >=3 repeats (cycles) per unit per arm; every arm sees the same
  sequence in the same declared order; difficulty above smoke by
  construction (release tier).
- Primary metric: success — the independent mechanical checker verdict.
  Secondary: time-to-correct (wall seconds to PASS), cost (worker
  session USD + orchestrator-side USD — hooks fire on orchestrator and
  workers), false-proven (a PASS the checker later refutes).
- Stop rule: fixed N (no peeking, no early stop); per-run caps only.
  A run that exhausts budget or wall counts as its outcome (exhaustion
  is a FAIL in the denominator — the pass@k ruling).
- Termination re-measurement: the pre-fix smoke observation (loop arms
  4/4 hit the 180s wall, CC 3/4 completed) is re-measured per arm under
  the post-fix budget faces; the report shows wall-hit / BLOCKED rates
  beside the success table.

## The decision rule

- H1 > H0 => execute the slimming list (versioned change, receipt
  attached).
- H2 > H1 => hand the listed decision set to the RL (same form).
- neither significant => the RL layer's scope is re-cut further (it is
  not the bottleneck; the harness's weight is not the lever).
Results are reported as-is, negative included.

## The runner extension (this card's code)

`scripts/eval_matrix_runner.py` gains `warm_up.store_mode` (default
`per-run`):

- `per-run` (unchanged): every (arm, unit) cell owns an isolated
  `<run_dir>/store`; warm cells each copy the source.
- `per-arm` (new): the arm's cells share ONE `<arm>/store`. The first
  unit materializes it (cold: empty dir; warm: one isolated copy of the
  source); every later unit reuses it with accumulated rows intact — a
  per-unit re-copy would wipe exactly the within-sequence learning the
  mode exists for. A warm dir that exists without its store file (a
  torn first materialization) is repaired by the copy.
- Arm isolation is structural: the store sits under the arm directory,
  so two arms can never share one. The scope binds store-bearing arms
  only — a cc face never reads the store, so its cells stay
  independent per-run plans.
- Launch cadence: an accumulating arm's cells ride ONE sequential
  launch group keyed by arm id — enforced for any plan order
  (concurrent cells would race the shared store); every other cell
  keeps the matrix's parallelism.
- The accumulating store persists across re-invocations into the same
  out dir (never wiped by the launcher): materialization is once per
  out dir — a fresh measurement uses a fresh out dir.
- The progress spine records the declared scope: `store_mode` at the
  doc level and on every accumulating cell's row.
- Hermeticity is untouched: the same stripped env, the same declared
  env merge, the same store-env handling.
