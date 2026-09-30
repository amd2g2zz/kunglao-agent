# EX-7 — kernel judgment: does the real DTS/q_cells kernel beat uniform?

Reproduce: `uv run --project . python experiments/ex7_kernel_judgment.py`
(raw numbers: `experiments/ex7-results.json`, same commit; deterministic —
byte-identity verified by a full rerun, sha256
`6bb9f60131ee20bbe8b9d0e8c8724f40a1cfcf8785f742a07624440683aa202c` over
the committed results). Pre-registration:
`openspec/changes/kernel-judgment-experiment/` (design + independent
design review, all amendments applied BEFORE the run; discriminators
evaluated exactly as pre-registered).

## Verdict, stated first: the kernel DOES beat uniform once fed data — barely, at the shipped γ; the drag is the discount + cold-family optimism, not a bug and not the state key

- **D4 fired (kernel healthy)**: kernel ≠ worse than uniform at n=100 in
  every regime, and statistically BETTER in 2 of 3 (R1 p=0.0001, R2
  p=0.018; R3 p=0.065 — one borderline miss). The strongest form of the
  owner's doubt — "no better than uniform" — is **rejected** in these
  worlds.
- **But the practical margin is small and late (D2 co-fired)**: at the
  shipped adaptive γ the kernel cuts regret by 0.8% (R1: 41.30 vs
  uniform 41.62), 0.4% (R2), 0.9% (R3) at n=100 — while trivial
  ε-greedy ε=0.1 cuts 76–85% (9.7–6.1 regret) and the pre-registered
  γ=1 diagnostic cuts 13–30% (29.3–36.1). Nothing separates before
  n=10–50 anywhere.
- **D1 (implementation defect) NEGATIVE**; **D3/D3′ (state-key sign
  flip) NEGATIVE** — the (signature_hash, family) cell with capped
  family-global anchoring beats uniform even in the class-specific
  world (R2), where the anchors point the wrong way for most classes.
  The anchor cost shows as magnitude (γ=1 regret 36.1 in R2 vs 29.3 in
  R1), never as a sign flip; per-class cuts contain no class where the
  kernel reliably loses.

## Deviation note (run 1, discarded) — published as loudly as the win

Run 1 fired D1 with kernel EXACTLY uniform everywhere. The
pre-registered trace audit found the defect in THIS HARNESS, not the
kernel: `q_cells.InMemoryStore` **copies** the rows iterable at
construction, so the arm's later `rows.append(...)` never reached the
fold — the kernel sampled cold Beta(1,1) posteriors for the entire
run, which is bit-for-bit uniform under a flat P_LLM. Per the
pre-registered crash/look protocol (design Decision 9): the harness was
fixed (store rebuilt per act through the public protocol), a
learning-sensitivity test pin was added
(`tests/test_ex7_kernel_judgment.py::test_kernel_arm_feeds_store_and_learns`),
and the WHOLE run restarted from scratch. All numbers above are run 2.
D1's trigger did its job — it caught a real (harness) defect.

## Verdict table — mean cumulative regret per class (n=5/10/25/50/100), sign tests vs uniform (200 paired seeds, two-sided exact, α=0.05)

| regime | arm | n=5 | n=10 | n=25 | n=50 | n=100 | verdict @100 |
|---|---|---|---|---|---|---|---|
| R1 aligned-sparse | kernel | 2.05 | 4.10 | 10.27 | 20.63 | **41.30** | **A_BETTER** (127–72, p=1e-4) |
| | kernel-g1 | 2.00 | 3.84 | 8.69 | 15.97 | **29.25** | **A_BETTER** (200–0) |
| | eps-greedy | 1.82 | 3.26 | 5.87 | 7.57 | **9.81** | **A_BETTER** (200–0) |
| | uniform | 2.08 | 4.17 | 10.44 | 20.85 | 41.62 | — |
| R2 class-specific-sparse | kernel | 2.07 | 4.15 | 10.38 | 20.76 | **41.49** | **A_BETTER** (115–81, p=0.018) |
| | kernel-g1 | 2.05 | 4.09 | 9.98 | 19.20 | **36.06** | **A_BETTER** (200–0) |
| | eps-greedy | 1.83 | 3.25 | 5.83 | 7.53 | **9.75** | **A_BETTER** (200–0) |
| | uniform | 2.09 | 4.19 | 10.44 | 20.87 | 41.67 | — |
| R3 dense-easy | kernel | 1.98 | 3.97 | 9.89 | 19.83 | **39.61** | NO_SEPARATION (113–86, p=0.065) |
| | kernel-g1 | 1.98 | 3.91 | 9.50 | 18.19 | **33.95** | **A_BETTER** (200–0) |
| | eps-greedy | 1.40 | 2.13 | 3.05 | 4.07 | **6.09** | **A_BETTER** (200–0) |
| | uniform | 1.99 | 4.01 | 10.04 | 20.08 | 39.97 | — |

First-separation horizon (kernel vs uniform, regret): R1 n=10, R2
n=100, R3 n=50 (the n=100 cell there is a borderline miss at p=0.065 —
wins 113–86 — after separating at n=50; secondary cells carry no gate
role and are reported as measured). Waste-acts before first success:
kernel A_BETTER in R1 (117–81), NO_SEPARATION in R2/R3.

## Discriminators, exactly as pre-registered

| id | fired? | reading |
|---|---|---|
| D1 implementation defect | NO | kernel-g1 separates decisively in all regimes; the run-1 fire was the harness deviation above |
| D4 kernel healthy | **YES (headline)** | better than uniform at n=100 in ≥2 regimes, worse nowhere |
| D2 vocabulary/sparse-reward drag | **YES (co-fired, early-drag clause)** | no separation before n=10–50 while ε-greedy separates at n=5; the 12-arm cold-family Beta(1,1) optimism + sparse Bernoulli reward starve early learning |
| D3 state-key flip (shipped γ) | NO | no n where kernel is WORSE in R2 while BETTER in R1 |
| D3′ state-key flip (γ=1) | NO | g1 is BETTER in R2 at every n; anchor cost is magnitude, not direction |

## Mechanistic reading (against the pre-registered expectations)

All three pre-registered expectations (design Decision 9) held: (i) the
shipped adaptive γ retains ≈5.6 pseudo-observations over an 800-row
stream — the kernel-vs-uniform regret gap at shipped γ (0.2–1.7 units)
matches an almost-amnesiac learner, while γ=1 triples-to-quadruples
the cut; (ii) the anchor-harm channel never flipped a sign — the state
key holds; (iii) kernel-g1 is the sensitive instrument and it is the
one that separates everywhere (200–0 sweeps at n=50–100 in all three
regimes). The remaining gap between kernel-g1 (13–30% cut) and
ε-greedy (76–85% cut) is the vocabulary/shrinkage architecture itself:
SHRINK_CAP=8 pseudo-observations of family-global anchor + Beta(1,1)
cold arms deliberately slow specialization — the documented
borrowing-strength design, priced here in regret.

## Real-data floor calibration (the mined feature-table/1)

NO_SEPARATION, exactly as pre-registered: 400 trials, 400 ties, 0 wins
0 losses — the fixture golden table's two usable runs have disjoint
method vocabularies, so every drawable first act scores p=0 under both
arms (the EX-5 substrate finding, now on the kernel-vs-uniform axis).
This cell is the honest floor: at current in-repo table scale, real
data cannot adjudicate the kernel either way; the harness reports that
as the null it is.

## Scope limits (what this does NOT settle)

- Bernoulli 0/1 credits; the production r_r rail is fractional — the
  learner was on trial, not the rail.
- Flat P_LLM (the W4 uniform fallback): the measured proposal channel
  was deliberately excluded (the design review's leakage ruling); a
  good prior could widen or narrow every margin above.
- 8 synthetic classes × 100 acts; production signatures churn faster
  (the obstacle dim re-keys mid-workspace per #461), which shortens
  effective cell life and would push toward the EARLY horizons — where
  the kernel is still uniform-like.
- No production change follows from this experiment: the γ schedule,
  SHRINK_CAP, and vocabulary are untouched; if the owner wants the
  γ=1-level margins, that is a separate ADR-001-governed calibration
  card, not a side effect here.
