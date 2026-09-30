# kernel-judgment-experiment — spec delta: kernel-judgment

## ADDED Requirements

### Requirement: The kernel-judgment experiment exercises the real kernel

EX-7 SHALL ship as `experiments/ex7_kernel_judgment.py` calling the
landed kernel code paths directly — `rlvr.q_cells.sample_method_family`
with the shipped default γ schedule, the closed #432 registry as the
arm vocabulary, and `rlvr.state.signature_hash` for the state key —
against a uniform-random control and an ε-greedy ε=0.1 learnability
calibration under paired environment randomness. The kernel SHALL NOT
be mocked, wrapped, or re-parameterized by the harness.

#### Scenario: the real sampler is the subject

- **WHEN** the harness draws a kernel arm
- **THEN** the family comes from `rlvr.q_cells.sample_method_family`
  over a `q_cells` store fed only by the policy's own observed
  outcomes, and the arm set is `method_families.registered_tokens()`

#### Scenario: rerun is byte-identical

- **WHEN** the experiment runs twice from the same commit
- **THEN** `experiments/ex7-results.json` is byte-identical

### Requirement: Pre-registration precedes the run and losses publish

The change's `design.md` SHALL fix the world regimes, ground-truth
constants, arm set, metrics, primary endpoints, stopping rule
(horizon, seed count, run-once), and the failure-mode discriminators
BEFORE the experiment executes, and the executed run SHALL be reported
as-is. The synthetic world SHALL NOT be re-tuned after kernel results
are observed; a kernel loss SHALL be reported with the same prominence
as a win.

#### Scenario: the stopping rule is fixed

- **WHEN** the harness runs
- **THEN** it uses exactly the pre-registered horizon (100 acts per
  class) and seed count (200 per regime), once, with no interim looks

#### Scenario: a losing kernel is the verdict

- **WHEN** the kernel does not beat uniform at the primary endpoints
- **THEN** the report states the loss in its opening summary and the
  discriminator table names the implicated failure mode

### Requirement: No answer leakage into policy inputs

The ground-truth success table SHALL reach a policy only through
Bernoulli outcomes of that policy's own chosen arms. Kernel inputs
SHALL be limited to the class signature hash, a class-independent
flat candidate prior, the policy's own store rows, and its rng.
Environment randomness SHALL be keyed without any policy term so that
identical (step, class, family) draws observe identical outcomes under
every policy.

#### Scenario: the prior carries no class information

- **WHEN** the kernel samples for any class
- **THEN** the candidate prior is the same flat distribution over the
  registered vocabulary for every class

#### Scenario: environments are paired

- **WHEN** two policies draw the same family for the same (regime,
  seed, step, class)
- **THEN** both observe the same outcome

### Requirement: Sign-test statistics with pre-registered endpoints

Arm comparisons SHALL use two-sided exact binomial sign tests over
exactly 200 paired seeds per cell (never more, never fewer) at
α=0.05, with the kernel-vs-uniform mean cumulative-regret comparison
at n=100 per regime as the ONLY primary endpoints; all other cuts
(horizons, metrics, arms, per-class) SHALL be reported as
secondary/diagnostic with raw p-values and no gate role.

#### Scenario: primary endpoints are the verdict carriers

- **WHEN** the verdict table is produced
- **THEN** each regime's verdict follows its one primary endpoint, and
  secondary cuts never override it

### Requirement: Real-data floor calibration over the mined table

The experiment SHALL include a paired kernel-vs-uniform replay over
the committed mined `feature-table/1` fixture using EX-5's
leave-one-run-out protocol, and SHALL report NO_SEPARATION at current
table scale as the honest expected floor rather than massaging it.

#### Scenario: the tiny table reports null as null

- **WHEN** the replay table has fewer than 3 usable runs
- **THEN** the replay block reports the floor result without claiming
  adjudication power it does not have
