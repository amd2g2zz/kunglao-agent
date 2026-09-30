# Design — kernel-judgment-experiment (EX-7)

## Decision 0: what is on trial

The SUBJECT is the landed kernel, imported and called as-is:

- `rlvr.q_cells.sample_method_family` — DTS call site 2 (the sampler),
- `rlvr.q_cells.fold` + `cell_posterior` — the γ-discounted read face
  and the hierarchical shrinkage (SHRINK_CAP=8.0 as shipped),
- `rlvr.posteriors.default_schedule` — the shipped adaptive DTS
  schedule (floor 0.8, EMA λ 0.9), via `gamma=None`,
- `scripts/method_families.py registered_tokens()` — the closed #432
  action vocabulary (12 tokens) as the arm set,
- `rlvr.state.signature_hash` — the real state-key derivation over
  state-sig/2 snapshot documents.

Nothing of the above is mocked, wrapped, or re-parameterized. The
experiment code builds worlds and stores AROUND them. A kernel loss is
a finding about the kernel, not about this harness.

## Decision 1: the world (synthetic, pre-registered)

**Signature classes** — the 8 eval-fixture release families
(`eval/v1/tasks/release/`): `arm-kdf`, `mod-crypto-js`, `mod-crypto`,
`net-verify-license`, `req-sign`, `smc-x86`, `web-pack-sign`, `win-kdf`.
Each class gets ONE canonical state-sig/2 snapshot document (per-class
index i ∈ 0..7: `facts={count:i+1, verified:i, bucket:i%6}`,
`claims={pattern:"OPEN=%d"%(i+1)}`, `budget={fraction:0.0, bucket:0,
present:False}`, `chain={k:i, n:8}`, `phase="DISPATCH"`,
`obstacles={present:False, count:0, kinds:""}`, `sides={}`) hashed
through the REAL `rlvr.state.signature_hash`. The 8 hashes are
distinct; classes are pure labels for the policies.

**Action space** — the 12 registered #432 tokens, loaded from the real
registry at run time (a registry change changes the experiment, which
is correct: the vocabulary is part of the subject).

**Ground truth** — per (class, family) success probability
`p[class][family]` from a sparse mixture: a few strong arms per class
(`p_strong`), everything else weak (`p_weak`). Strong-arm sets are
drawn deterministically
(`random.Random("ex7/world/<regime>/<class>")`, `sample` without
replacement over the sorted vocabulary).

Three regimes (ALL constants fixed here, before any run):

| regime | name | strong arms | p_strong | p_weak | strong-set rule |
|---|---|---|---|---|---|
| R1 | aligned-sparse | 2 | 0.55 | 0.05 | the SAME 2 families for every class (`Random("ex7/world/R1/shared")`) — family-global signal |
| R2 | class-specific-sparse | 2 | 0.55 | 0.05 | each class draws its own 2 (`Random("ex7/world/R2/<class>")`) — state key REQUIRED |
| R3 | dense-easy | 4 | 0.75 | 0.15 | each class draws its own 4 (`Random("ex7/world/R3/<class>")`) — high signal, tests learning speed |

R1 vs R2 is the designed contrast for the state-key discriminator
(D3): in R1 the family-global anchor the shrinkage borrows from points
the right way; in R2 it points the wrong way for most classes and only
per-signature cell evidence can win.

**Outcomes** — Bernoulli(p[class][family]) draws, credit ∈ {0.0, 1.0},
appended to the acting policy's own store as `q-cell-obs/1`
settlement rows (`source="settlement"`) — the W5 wiring shape. The
world NEVER writes to another policy's store.

**Trajectory** — per seed: 8 classes round-robin, 100 acts per class
(800 steps total, class of step t = classes[t mod 8]); checkpoints at
per-class n ∈ {5, 10, 25, 50, 100}.

## Decision 2: honesty of the outcome model (no answer leakage)

The ground-truth table reaches a policy ONLY through Bernoulli
outcomes of its OWN chosen arms. The complete kernel input list at
every step is: (a) the class's signature hash (a label), (b) the flat
candidate prior `{family: 1.0 for family in sorted(registered)}`
(mirrors the W4 "uniform over the registered vocabulary" production
fallback — P_LLM carries NO class information), (c) the policy's own
store rows, (d) its rng. No policy input is derived from
`p[class][*]`, from another policy's behavior, or from the env RNG.

**Paired environments**: outcome randomness is keyed
`random.Random("ex7/env/<regime>/<seed>/<t>/<class>/<family>")` — no
policy term. Two policies drawing the same (t, class, family) see the
SAME outcome, so arm-for-arm comparisons are paired, not two
independent Bernoulli streams (the EX-5 paired-env fold). World seeds
(`ex7/world/...`) and policy seeds (`ex7/policy/...`) are disjoint
namespaces.

**Regime learnability is calibrated, not assumed**: ε-greedy ε=0.1 over
a plain per-(class, family) Beta(1,1) mean is the floor-learner
anchor. A regime where ε-greedy never separates from uniform is a
regime without learnable signal, and kernel ≈ uniform there is
uninformative — the report marks such cells explicitly.

## Decision 3: the four arms

1. **kernel** — `q_cells.sample_method_family(sig, flat_prior, store,
   rng=policy_rng, gamma=None)` per act; append the observed row to
   `store` (a real `q_cells.InMemoryStore` grown in place).
2. **kernel-g1** — the same call with `gamma=1.0` (the constant-γ
   calibration face): a PRE-REGISTERED diagnostic that separates
   "DTS discount suppresses learning" from "learner cannot learn"
   inside discriminator D2.
3. **uniform** — `policy_rng.choice(sorted(registered))`; identical
   store bookkeeping (for symmetry of measurement code, not because
   the control needs it).
4. **eps-greedy** — ε=0.1: with prob 0.1 uniform arm (own rng), else
   argmax over its OWN tracked Beta(1,1) means `(s+1)/(s+f+2)` per
   (class, family); ties broken by rng among the argmax set.

All arms act on identical step schedules; the env RNG pairing makes
outcomes arm-deterministic.

## Decision 4: metrics, censoring, and the statistics

Per (regime, seed) each arm records, per class and checkpoint n:

- `cumulative_regret(class, n)` = Σ over the class's first n acts of
  (p_best(class) − p(class, chosen)); trajectory scalar = mean over
  the 8 classes (sign-test unit). Per-class values are kept for D3.
- `waste_before_first_success(class, n)` = failed acts in the class
  before its first success, censored to n when no success yet.
  Censoring comparison: success beats censored; censored(n) vs
  censored(n) is a tie; trajectory scalar = mean over classes.
- `first_success_index(class, n)` = 1-based index of the first
  success within the class's own act sequence (null while censored);
  reported descriptively (it is waste's mirror; waste carries the
  sign test).

**Sign tests** — EXACTLY 200 seeds per regime (seed ids 0..199, never
more, never fewer), paired per seed: two-sided exact binomial sign
test on the trajectory MEAN-OVER-CLASSES scalar of each metric,
ties dropped, α=0.05. The per-class success-beats-censored comparison
rule is a D3/D3′ diagnostic cut only, never a sign-test input; tie
counts (censoring saturates at n=5/10 for the waste metric) are
reported per cell. Verdict labels per cell: `A_BETTER`, `A_WORSE`,
`NO_SEPARATION` — and NO_SEPARATION ≠ equality: at n=200 the test
detects win fractions ≳57%; sub-threshold effects are reported as
such, not as nulls of equality.

**Primary endpoints (pre-registered, at most 3 tests carry the
verdict)**: kernel vs uniform on mean cumulative regret at n=100, one
test per regime. No multiplicity correction across the three: each
adjudicates its own regime and D4 is conjunctive across them. Everything
else (other horizons, metrics, arms, per-class cuts) is pre-registered
SECONDARY/diagnostic output with raw p-values reported and no gate
role — the horizon sweep exists to date WHEN separation appears (D2),
not to fish for it.

**Stopping rule** — fixed: horizon 100/class, EXACTLY 200 seeds/regime
(always), run ONCE from the committed harness. No interim looks, no
seed top-ups or seed cuts under any circumstance (a slow run waits,
e.g. in the background; the seed count never changes), no post-hoc
regime edits. The kernel losing is a publishable result, not a re-run
trigger.

## Decision 5: pre-registered failure-mode discriminators

Written BEFORE the run and amended BEFORE the run per the independent
design review (see `design-review.md`): D1 is gated on the γ=1
diagnostic (a kernel that fails only under discount is not an
implementation defect), D2 covers the never-separates-under-shipped-γ
case, D4 outranks D2 (an early-horizon drag note must not shadow a
healthy n=100 verdict), and D3′ is the γ=1-face state-key instrument
(the shipped-γ arm is too amnesiac at this horizon — measured ≈5.6
pseudo-observations of retained evidence over an 800-row stream, per
own-class-act decay γ^8 under the 8-class interleave — to express
anchor harm reliably).

**Precedence for the headline verdict: D1 > D4 > D2 > D3 > D3′. ALL
fired rows are reported; precedence only orders the headline.** If
nothing fires, the report says "no discriminator fired" as its own
row.

| id | trigger (exact) | verdict |
|---|---|---|
| D1 | kernel vs uniform = NO_SEPARATION at n=100 in R3 **AND kernel-g1** vs uniform = NO_SEPARATION at n=100 in R3 **while** eps-greedy vs uniform = eps_BETTER at n≤25 in R3 | implementation defect — unit-level trace audit (fold γ weights, cell_posterior anchor/shrinkage, sampler P_LLM·θ weights, cumulative selection loop). If kernel-g1 separates while kernel does not, this row does NOT fire (that case is D2's γ-drag clause) |
| D4 | kernel vs uniform ≠ kernel_WORSE at n=100 in ALL regimes AND kernel_BETTER at n=100 in ≥2 regimes | kernel healthy — separation exists once fed data; report effect sizes honestly; D2 may co-fire as the early-horizon drag note without shadowing this verdict |
| D2 | (a) kernel separates from uniform only at n≥25 (NO_SEPARATION at 5/10) in R1/R3 with eps-greedy separating at n≤10 — early-drag clause; OR (b) kernel = NO_SEPARATION at n=100 in R1/R3 while kernel-g1 separates at ANY n — γ-drag-dominant clause | vocabulary/sparse-reward drag — the 12-arm coarse vocabulary + sparse Bernoulli reward starves the learner; in clause (b) the adaptive-γ discount is the dominant component (kernel-g1 closing the gap is the instrument) |
| D3 | kernel vs uniform = kernel_WORSE in R2 at any n while kernel_BETTER in R1 at that n (sign flip across regimes, shipped-γ face) | state key — the (signature_hash, family) cell + family-global anchor pool transmits cross-class structure that per-class truth contradicts; per-class cuts must show losses concentrated where class strong-arms disagree with family-global mass |
| D3′ | kernel-g1 vs uniform = g1_WORSE in R2 at any n while g1_BETTER in R1 at that n (sign flip at the γ=1 face) | state key (γ=1 instrument) — the same architectural verdict as D3, read where the anchor masses actually persist; may fire when D3 cannot |

D3/D3′ firing without D4 means a genuine structural finding: the
borrowing architecture helps only when the world is family-aligned,
and the state key does not rescue it within 100 observations.

## Decision 6: real-data floor calibration (the mined table)

Replay over the committed mined `feature-table/1`
(`tests/fixtures/feature-mining-460/golden/feature-table.jsonl`),
EX-5's leave-one-run-out protocol, arms = kernel (flag-off, shipped
γ default) vs uniform over the training pool's candidate vocabulary
with the measured proposal prior; 200 seeded trials per run per arm,
paired env RNG keyed `ex7/replay/env/<run>/<trial>/<family>`.
Metric: first-act success rate. **Expected: NO_SEPARATION** — the
table's two usable runs have disjoint method vocabularies (EX-5
finding), so nothing can adjudicate the kernel there. This cell is the
honest floor: it demonstrates the harness reports null results as
nulls, and it sizes what "real data" means today.

## Decision 7: reproducibility and artifacts

- Every RNG is `random.Random(<fixed string>)`; no wall clock, no
  OS entropy. Rerun ⇒ byte-identical `ex7-results.json` (sha256
  recorded in the report).
- `ex7-results.json` carries schema `ex7-kernel-judgment/1`, the
  regime ground-truth tables, per-arm aggregates, per-cell sign tests,
  the discriminator evaluation, and the replay block.
- `ex7-kernel-judgment.md` renders the verdict table (regime ×
  horizon × arm) and the fired discriminators; losses stated in the
  first paragraph, not the appendix.
- `tests/test_ex7_kernel_judgment.py` pins: world determinism (same
  constants ⇒ same ground truth), env pairing (same (t, class, family)
  ⇒ same outcome under any policy label), a micro-run (2 seeds from
  ids 9000–9001, horizon 5 — outside the real seed range per Decision
  9) executing the real kernel end-to-end, and the results-JSON
  schema shape.

## Decision 8: risks

- The fold is O(rows) per sampler call and `family_mass` rescans all
  cells per candidate family, so the full grid is roughly 10^9-scale
  Python dict/dataclass operations (the design review benchmarked the
  order of magnitude) — expect tens of minutes, not single-digit.
  The seed count NEVER changes to save time (Decision 4): a slow run
  waits in the background.
- Bernoulli 0/1 credits are the simplest credit rail; real r_r is
  fractional. This experiments on the LEARNER, not the rail — stated
  as a scope limit in the report.
- 8 synthetic classes cannot stand for all workspace diversity; the
  real-data replay is the only in-repo bridge to production data, and
  it is (honestly) tiny.

## Decision 9: crash and look protocol (pre-registered)

- **Mid-run crash or harness bug**: restart the WHOLE run from scratch
  (string-keyed RNGs make restart byte-safe); partial results are
  never inspected or carried forward.
- **Any harness fix made after results were seen** ships as a named
  deviation in the report, with what was seen before the fix.
- **Test isolation**: the committed test's micro-run uses seed ids
  OUTSIDE 0..199 (9000-9001) and horizon 5, so no test execution ever
  observes a real grid cell before the single pre-registered run.
- **Pre-registered mechanistic expectations** (from the design
  review's live measurements, so neither outcome gets rationalized
  post-hoc): under the shipped adaptive γ and the 8-class interleave,
  total retained fold mass over an 800-row stream is ≈5.6
  pseudo-observations (per own-class-act decay γ^8 ≈ 0.20–0.47); a
  cell last played 96 rows earlier retains ~10^-6. Consequences
  pre-registered: (i) under shipped γ, local cell evidence cannot
  outgrow the SHRINK_CAP=8 anchor within this horizon — kernel
  NO_SEPARATION at n=100 is a plausible CORRECT-kernel outcome, which
  is exactly why D1 is gated on kernel-g1; (ii) the anchor-harm
  channel (D3) may be undetectable at the shipped-γ face, which is
  why D3′ exists; (iii) kernel-g1 is the sensitive instrument for
  both the vocabulary and state-key questions.
