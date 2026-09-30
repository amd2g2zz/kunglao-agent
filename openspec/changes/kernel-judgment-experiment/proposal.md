# Proposal — kernel-judgment-experiment

## Why

The owner expressed fundamental doubt about current RL capability and
demanded a falsification gate: does the landed DTS/q_cells kernel
(#429/#428/#432/#466 actuation) actually outperform UNIFORM arm
selection once it is fed data — and if it does not, WHICH failure mode
is it: an implementation defect, a coarse action vocabulary starving
the learner, or a wrong state key? Everything downstream of the kernel
(feature priors #460, obstacle attribution #461, strategy composition
#431) tunes a loop whose core learning claim has never been adjudicated
against even the dumbest baseline. EX-5 adjudicated the feature-prior
DELTA, not the kernel itself; no experiment to date answers "is the
kernel better than uniform at all".

## What changes

- **EX-7** `experiments/ex7_kernel_judgment.py` — an offline
  Monte-Carlo judgment experiment over the REAL kernel code paths
  (no mocking: `rlvr.q_cells.sample_method_family` / `fold` /
  `cell_posterior` / the #432 registry / `rlvr.state.signature_hash`
  are imported and called as landed on dev). Signature classes come
  from the eval-fixture release families; the action space is the
  closed #432 vocabulary; ground-truth success probabilities per
  (class, family) are drawn from a sparse mixture under three
  parameterized regimes. Four arms run under paired environment
  randomness: the kernel (shipped default γ schedule), a kernel-γ=1.0
  diagnostic arm, uniform random, and ε-greedy ε=0.1 as the learnability
  calibration. Metrics at n=5/10/25/50/100 outcomes per class:
  cumulative regret, waste-acts before first success, first-success
  act index; two-sided exact sign tests across ≥200 paired seeds per
  cell.
- **Pre-registration discipline**: `design.md` fixes the metrics, the
  synthetic outcome model, the honesty argument (no answer leakage into
  policy inputs), the stopping rule, and the failure-mode discriminators
  BEFORE the experiment runs; the run is executed once and its result —
  win or loss — is the deliverable. The synthetic world is never re-tuned
  after seeing kernel results.
- **Real-data floor calibration**: a paired kernel-vs-uniform replay
  over the mined `feature-table/1` (the committed Part-A fixture
  golden, EX-5's substrate) where NO separation is the expected and
  honest result at current table scale.
- Artifacts: `experiments/ex7-results.json` (committed raw numbers) +
  `experiments/ex7-kernel-judgment.md` (report with the verdict table);
  `tests/test_ex7_kernel_judgment.py` pinning determinism and the
  no-leakage pairing property.

## Non-goals

- No production code changes: the kernel, hooks, gates, and every
  `scripts/` module are imported read-only. If the kernel loses, the
  verdict IS the deliverable — no kernel edits hide in this change.
- No flag flips, no registry edits, no new method-family tokens.
- No attempt to make the kernel win: the world's parameters are fixed
  by this proposal's design and never revisited post-hoc.
- Not an activation gate for `KUNGLAO_PREDICT_BEFORE_TRY` (that is
  EX-5's face); the kernel arms here run flag-off.

## Experiment numbering

The in-repo experiments ledger carries EX-2..EX-5; EX-6 is reserved by
an out-of-repo measurement ledger, so this experiment takes **EX-7**.
