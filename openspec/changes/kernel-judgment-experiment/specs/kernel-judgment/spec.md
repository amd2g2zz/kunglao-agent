# kernel-judgment

## ADDED Requirements

### Requirement: ex7-verdict-artifacts
EX-7 SHALL produce experiments/ex7_kernel_judgment.py + ex7-results.json + ex7-kernel-judgment.md whose report contains the verdict table (per regime × n × policy: regret/waste/first-success, sign tests) and each pre-registered discriminator marked fired/not-fired, runnable deterministically (fixed seeds; byte-identical reruns).

#### Scenario: deterministic rerun
- **WHEN** the experiment script runs twice
- **THEN** the results JSON is byte-identical

#### Scenario: degenerate control ties
- **WHEN** regime R2 (no signal) runs
- **THEN** kernel and uniform regret differ by no more than noise (sanity discriminator)
