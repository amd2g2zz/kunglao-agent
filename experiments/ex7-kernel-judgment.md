# EX-7 — Kernel Capability Judgment (200 paired seeds, pre-registered)

**The owner's doubt, answered with data:** the kernel is REAL but not yet the best cheap option.

## Verdict table (cumulative regret, lower is better; sign = fraction of paired episodes where kernel < uniform)

| Regime | n | kernel | uniform | ε-greedy | sign(k<u) |
|---|---|---|---|---|---|
| R1 sparse-strong | 5 | 2.673 | 2.760 | 2.317 | 0.527 |
| R1 | 25 | 12.611 | 13.771 | 9.693 | 0.717 |
| R1 | 100 | **48.768** | 55.164 | **23.887** | **0.918** |
| R2 degenerate (control) | 100 | 3.974 | 4.016 | 3.782 | 0.552 |
| R3 one-dominant | 25 | 16.300 | 17.330 | 14.029 | 0.676 |
| R3 | 100 | **64.133** | 69.247 | **40.804** | **0.884** |

## Pre-registered discriminators (design.md, written before any run)
1. kernel ≈ uniform at n=100 → implementation defect: **NOT FIRED** — the engine genuinely learns (sign 0.92/0.88 in the signal regimes).
2. separation only at large n → vocabulary/reward sparsity: **FIRED (partial)** — no separation at n=5 (0.53), meaningful from n=25 (0.72), decisive at n=100 (0.92). The kernel needs ≥25 outcomes per signature-class before its choices beat blind chance by a wide margin.
3. sign flips across classes → state-key problem: **NOT FIRED**.
4. kernel > uniform but < ε-greedy → sampling noise too high: **FIRED — the headline finding.** ε-greedy (0.1) roughly HALVES the kernel's regret at n=100 (23.9 vs 48.8 in R1; 40.8 vs 64.1 in R3). Thompson-style persistent exploration is too expensive at 8 arms / n≤100 compared to quick lock-on.
5. R2 sanity (no-signal world must tie): **HOLDS** (sign 0.55 — no false signal; the engine does not hallucinate structure).

## What this means
- The DTS/q_cells machinery is not placebo: it beats uniform decisively once fed, and stays honest when there is nothing to learn.
- It is ALSO not yet the best available cheap policy: a trivial ε-greedy dominates it at realistic per-class data volumes. Exploration is the cost driver.
- Consistent with the live experience: the 2-run feature table cannot feed a policy that needs ≥25 outcomes/class to shine.

## Follow-up options (decision for the owner; NOT tuned here per the honesty rules)
A. Exploitation-lean kernel: sharpen P_LLM⊗Q toward posterior mean (less Thompson spread) — the γ floor and the weight product are the knobs.
B. Hybrid: ε-greedy skeleton with the kernel's cells as the ranking prior (keep cross-signature transfer, drop per-draw exploration).
C. Accept as-is where uniformity is the alternative (kernel still beats the status quo) and revisit after the feature flywheel thickens data.

Determinism: fixed seeds; `--seeds 200` reproduces ex7-results.json byte-identically (2:14 runtime).
