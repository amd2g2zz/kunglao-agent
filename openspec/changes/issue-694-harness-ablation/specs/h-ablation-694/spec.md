# h-ablation-694 delta — issue-694-harness-ablation

## ADDED Requirements

### Requirement: The ablation is pre-registered before the first run

The three-arm ablation SHALL have a protocol file under
`experiments/exp-s11-h-ablation/` (local-only) written BEFORE the first
run, fixing: the arms and their realization, the task sequence, the
repeat count (>=3 per task), the metrics, the stop rule, and the
decision rule. Amendments after the first run SHALL NOT rewrite the
protocol — post-run deviations SHALL be reported as deviations, never
folded silently into the protocol.

#### Scenario: protocol precedes the first run

- **WHEN** the first run of any arm is launched
- **THEN** `experiments/exp-s11-h-ablation/` exists and already carries
  the arms, sequence, N, metrics, and stop rule as frozen text

#### Scenario: a post-run change is a deviation, not an edit

- **WHEN** the analysis needs to change a metric or drop a cell
- **THEN** the change is reported as a deviation with its rationale in
  the results, and the original protocol text remains on record

### Requirement: The three arms differ only in their declared faces

H0 SHALL be the registry's bare-Claude-Code face (`cc-bare`, no plugin,
no store). H1 SHALL run the slim harness (the five kept faces only, the
decision-for-policy items demoted per the keep/cut table) with every
learned decision input off. H2 SHALL run the same slim harness with the
listed decision set handed to the RL layer. All three arms SHALL share
one frozen model alias, one tool supply, one per-run budget cap, one
independent checker, and one task sequence.

#### Scenario: H2 differs from H1 only in the decision set

- **WHEN** the H2 configuration is compared against the H1 configuration
- **THEN** the diff is exactly the decision-for-policy set routed to
  the RL (family via the sampler with a logged propensity, posterior
  rank, capability-switch with a recorded reason) and nothing else

#### Scenario: the pre-fix termination receipts are context only

- **WHEN** the report discusses termination
- **THEN** the pre-ACT-BUDGET smoke receipts appear as historical
  context and the termination gap is re-measured under the post-fix
  budget faces in this ablation

### Requirement: The five-face keep/cut criterion governs every slimming item

Each slimming candidate SHALL carry an explicit verdict against the
five-face criterion (reward integrity / termination and budget /
evidence and execution classes / observation and telemetry / execution
surface): an item that serves a face is KEPT; an item that decides for
the policy carries a non-KEEP verdict — advisory, decided-with-reason,
rescoped, or REMOVED — written in the keep/cut table.

#### Scenario: a policy-deciding enforcement is demoted, not kept

- **WHEN** an item's only effect is to decide FOR the policy (claim
  order, method family, action bans)
- **THEN** the keep/cut table carries an explicit non-KEEP verdict for
  it — advisory, decided-with-reason, rescoped, or removed — and the
  slim snapshot realizes exactly that verdict

#### Scenario: a zero-value observation face is default-off, not deleted

- **WHEN** an item serves a kept face but measured zero value
- **THEN** it ships default-off and stays switchable — the face is not
  deleted for a measurement

### Requirement: The decision rule is fixed before the runs

The protocol SHALL fix the triage: H1 > H0 executes the slimming list;
H2 > H1 hands the listed decisions to the RL; neither significant means
the RL layer's scope is re-cut further. Any landing SHALL be a
versioned change with the ablation receipt attached. Results SHALL be
reported as-is, negative results included, and the cost metric SHALL
include the orchestrator side (hooks fire on orchestrator and workers).

#### Scenario: no silent authority transfer

- **WHEN** an ablation result would move decision authority
- **THEN** the move lands as a versioned change whose description cites
  the ablation receipt, never as a drive-by tweak

#### Scenario: negative results are reported

- **WHEN** neither comparison separates (or an arm loses)
- **THEN** the report states it plainly and the RL scope re-cut follows
  the fixed rule — no metric re-definition to force a winner
