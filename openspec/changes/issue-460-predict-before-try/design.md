# design — issue-460-predict-before-try (Part B)

## Verified anchors (2026-09-30, branch feat/predict-before-try-460b off origin/dev ea383376)

| Question | Actual | Drift |
|---|---|---|
| Where shrinkage lives | `scripts/rlvr/q_cells.py::cell_posterior(fold_view, signature_hash, family)` — anchor = family-global LEAVE-ONE-OUT mass pool, `w = min(SHRINK_CAP=8.0, n_anchor)`, posterior `Beta(1 + w·m + s_local, 1 + w·(1−m) + f_local)`; empty anchor → `(BASE_ALPHA + s, BASE_BETA + f)` | none |
| Who pins the kernel | `tests/test_q_cells_429.py` (shrinkage arithmetic at γ=1 exact fractions, sampling distribution χ², determinism, receipts) + `tests/test_rlvr_bitexact.py` (compute_priors / Normal-Gamma / receipts / continuity — 16 tests, none touch q_cells directly); settlement float determinism axiom = input-order float64 sums (`_seq_sum`, pairwise `np.sum` FORBIDDEN on this path) | none |
| What the sampler consumes | `sample_method_family(state_signature, candidates_with_llm_prior, store, rng=None, gamma=None)` — pure; the compose seam `strategy_store.PosteriorStrategyStore.method_lead` is its production consumer (#462 D3); e2e envelope synthesis is call site 2's act host (#462 D5) | none |
| The substrate contract | `scripts/feature_mining.py` emits `runs/feature-table.jsonl` rows schema feature-table/1: {run_id, family, task_id, signature_hash (=sha256[:12] over canonical features JSON — INSTANCE namespace, distinct from state_signature), features{lane, project_type, target_kind{language,entry_suffix}, packer_flags{4 booleans, detected_packers[], detected_obfuscators[]}, difficulty_factors|null, probe_outputs{die,apkid}}, outcomes[{claim, method_family_or_claim_source, act_result ∈ landed/timeout/blocked/unknown, settled, credit|null}]}; `validate_row` is the importable validator | none |
| The #669 probe-set gating surface | `scripts/intake_promise.py`: `_prescan(report)` keys on per-project_type toolchain-report membership — an item absent from THIS project_type's CHECK_SETS yields the note "layer not in this project_type's probe set - must still run at first claim (#669)"; `_prescan_obligation` pins the fixed first-claim rule, lane-gated via `NATIVE_OBLIGATION_LANES={malware}`; `OBLIGATION=["evidence/apkid.json","evidence/die.json"]`. Consumers of `promise.prescan`: none enforce it (advisory memo in task_spec; feature_mining reads the states as features). Toolchain CHECK_SETS = capability facts (KEPT — not the rule) | none |
| Probe arm vocabulary | `tools/_INDEX.yaml`: die-probe (cost_tier=probe, capability static:identify), apkid-prescan (cost_tier=cheap, android:packer-fingerprint); method arms = the #432 closed registry (`scripts/method_families.yaml`, 12 tokens) | none |
| Replay data availability | NO live `runs/e2e/<run_id>/run-state.json` anchors exist on any reachable root (checked /tmp/e2e workspaces — no run dirs; kunglao-wt — no runs/e2e; repo runs/ — empty). The ONLY mined table in-repo: `tests/fixtures/feature-mining-460/golden/feature-table.jsonl` — 3 sanitized runs, 2 with outcomes (e2e-fix-211504-a: static-decompile landed + synthesis settled credit 0.0; e2e-fix-221504-b: static_re timeout/blocked/unknown; e2e-fix-231630-c: no outcomes) | disclosed (Decision 6) |
| Flag idiom | `KUNGLAO_*` env vars read at call time (`KUNGLAO_PROBE_TIMEOUT_FLOOR`, `KUNGLAO_INIT_REPORT_KEEP`, …); no runtime-tunable constants on the kernel path (ADR-001 governance pattern — policy constants change with replay evidence + pins, never runtime self-tuning) | none |

## Decision 1: activation is a default-off flag; inert code is byte-identical code

`KUNGLAO_PREDICT_BEFORE_TRY` (env, read at call time by
`feature_prior.enabled()`; `"1"` = on, everything else = off; default
OFF). Every new code path is reachable ONLY when the flag is on AND its
own substrate is present (B1: a valid feature table + a features
vector; B2: the ranked-arms obligation face). Flag off OR substrate
absent ⇒ the kernel, sampler, receipts, and intake promise produce
byte-identical output to the pre-change tree — pinned by identity tests
in `tests/test_feature_prior_460b.py` (same store + seed ⇒ identical
receipt JSON). The flag is a single axis so the A/B is exactly
flag-on vs flag-off; flipping it default-on is an owner decision
recorded after the A/B (ADR-001), not a runtime knob.

## Decision 2: similarity = Jaccard over the canonical feature-token set

Every mined field is categorical, boolean, or set-valued (lane,
project_type, language, entry suffix, packer-flag booleans, detected
packer/obfuscator name sets, difficulty tier/dominant factor, probe
usability facts). There is no natural metric scale to standardize and
no ordinal distance to defend — so the features object is projected to
a canonical TOKEN SET and similarity is Jaccard:

```
tokens(F) = {"lane="+lane, "ptype="+t, "lang="+l, "entry="+s}   non-null scalars
          ∪ {"pf:"+flag}          for each TRUE packer_flag boolean
          ∪ {"pk:"+p} ∪ {"ob:"+o} detected packers / obfuscators
          ∪ {"tier="+t, "dom="+d} when difficulty_factors present
          ∪ {"die:usable"} / {"apkid:usable"}   when usable
          ∪ {"die:packer="+p}     when die detected_packer non-null
sim(A,B) = |A ∩ B| / |A ∪ B|        (0.0 when the union is empty)
```

Why Jaccard and not alternatives: (a) set intersection/union needs no
scaling, weights, or fitted distance hyperparameters — the audit trail
is two sets; (b) it is symmetric and bounded in [0,1], so a similarity
can be used directly as a pseudo-mass discount without transformation;
(c) NULL fields emit no tokens — missing evidence degrades to lower
similarity (less borrowing), never to fabricated distance (absence
never scored — the Part-A gap-rule idiom); (d) token identity is
string equality — deterministic, order-independent, no float
arithmetic. Hamming over a fixed field vector was rejected: the fields
have heterogeneous arity (a packer LIST vs a boolean) and Hamming
weights fields implicitly and evenly, which is a hidden hyperparameter;
cosine over one-hot vectors was rejected: it reduces to a monotone
function of Jaccard on set-valued data while carrying float arithmetic
on the deterministic path. Cold-start (no instance features) ⇒ empty
token set ⇒ union empty ⇒ sim = 0 for every pair — no borrowing, which
is exactly the honest posture (Decision 4 handles cold-start ordering
via information gain, not via phantom similarity).

## Decision 3: the feature pool is a second anchor source under the one SHRINK_CAP

The existing hierarchy is kept UNCHANGED as the base layer: family
global leave-one-out pool, weight 1 per observation, entering the cell
as at most SHRINK_CAP pseudo-observations. The feature-conditioned pool
is a SECOND anchor source, computed from the feature table:

```
pool(F, family) = Σ_rows  sim(F, F_row) · (success_row, failure_row)
                  over OTHER mined instances' outcomes attributed to
                  this family (the query's own instance excluded —
                  leave-instance-out; identical feature-hash rows are
                  other RUNS of the same task and DO pool)
success_row = credit          when settled (credit ≠ null)
            = 1.0 / 0.0       else act_result landed / (timeout|blocked)
            = excluded        else act_result unknown
cell_posterior(..., feature_pool) adds the pool masses to the anchor
masses BEFORE the single cap:
  s_anchor += s_pool ; f_anchor += f_pool
  w = min(SHRINK_CAP, n_anchor_total)     (unchanged formula)
```

Borrow weighting vs the existing shrinkage, stated plainly: the
family/global pool stays the BASE borrow (weight 1); the feature pool
rides ON TOP as similarity-discounted mass (each mined observation
enters at weight sim ≤ 1, so weakly-similar evidence barely moves the
anchor and the pool can only TILT the borrowed mean toward structurally
similar instances, never dominate local evidence — local evidence
outgrows the anchor exactly as before, under the same cap). Total
borrowing stays bounded by the ONE SHRINK_CAP=8.0: with no table the
anchor is exactly today's; with a table the anchor mixes both pools but
its total pseudo-observation weight never exceeds 8. Double-counting
cannot arise INSIDE one store: the q-cell fold reads
`runs/q-cell-log.jsonl` and the feature pool reads
`runs/feature-table.jsonl` — disjoint files; if both ultimately derive
from the same historical acts, the shared cap still bounds the anchor.
No new policy constant is introduced (reusing SHRINK_CAP — the ADR-001
governance pattern; a separate feature-cap would be a fitted knob with
no replay evidence behind it).

Ordering/float determinism: pool accumulation iterates table rows in
TABLE ORDER (the miner's canonical sort — byte-stable) and reduces
through `q_cells._seq_sum` semantics (input-order float64) — same input
bytes ⇒ same pool bits ⇒ same posterior bits. A pool of (0,0) masses
(all similarities zero) leaves the anchor bits UNCHANGED — pinned.

Leave-instance-out is the REPLAY's split, not the live face's filter
(review H1): at live sample time the query is a NEW instance — no
table row is "itself" — and a previous run with the IDENTICAL feature
hash is exactly the history the prior should pool (same task, more
data; that is borrowing, not leakage: the outcome already happened).
The A/B replay excludes its held-out run by EXPLICIT run id
(`pool_for(..., exclude_run=run_id)`); no fuzzy run-identity join
exists anywhere (the table rows and the live query share no run key).

Namespaces/pollution (review M2): pools are keyed by the table's
outcome `method_family_or_claim_source` string verbatim — claim-source
strings (synthesis, static_re…) are NOT #432 tokens, and sampler
queries ride the registered-token candidate set (#462 D5 intersects
candidates with the registry), so non-token pools are unreachable from
the sampler and can never pollute it; the A/B replay acts in the
observed vocabulary deliberately (it replays what history contains).

Wiring face (review M4): `cell_posterior(fold_view, signature_hash,
family, *, feature_pool=None)` — the new argument is keyword-only,
default None = today's math bit-for-bit (existing pins untouched). The
pool object is built by `feature_prior.pool_for(table, features,
family, exclude_run=None)`; the sampler `sample_method_family(...,
features=None, feature_table=None)` computes per-family pools and
passes them through ONLY when the flag is on and both inputs exist
(candidate-parallel, cost = O(candidates × rows) per sample — table
rows are the miner's output, small by construction; review M2b); the
receipt gains an additive
`"feature_prior": {"pool_success":…, "pool_failure":…, "rows":…}`
block on candidates (schema q-cell-sample/1 is additive-compatible;
existing receipt pins use `set(c) >= {…}` and stay green). The live
features vector comes from
`feature_prior.features_from_workspace(ws, task_dir=None)` — the SAME
extraction Part A pins (feature_mining._features over the live
task_spec/evidence), reused by import, never re-implemented; the live
face has NO corpus task_dir (that pointer lives in run-state, absent
at dispatch time), so target_kind degrades to nulls on the live face —
the absence idiom, disclosed (review M1). The production call sites
(#462 D3/D5: `strategy_store.method_lead` and the e2e envelope host in
`scripts/e2e/checkpoints.py`) thread `features_from_workspace(ws)` +
the workspace feature-table path WHEN the flag is on, fail-open on any
extraction error (review M4 — without this the flag-on path would be
dead code at the production seam).

## Decision 4: #669 retirement — capability facts stay, rules go; probes become prior-ranked arms

Split the current surface into facts and rules:

- FACTS (kept): toolchain CHECK_SETS capability probing (is the tool
  present — per project_type environment contract), the WARN-tier
  presence records, #436 resource-safety wrappers (orthogonal).
- RULES (retired): (a) the per-project_type probe-LIST membership rule
  in `_prescan` — "layer not in this project_type's probe set" keyed on
  whether THIS type's CHECK_SETS happened to emit the item. This note
  and its membership coupling are DELETED unconditionally: the prescan
  block records a DIRECT capability fact for BOTH probe tools on every
  lane/type with one uniform fallback chain, exact mapping pinned
  (review M3): toolchain item present → state from the item (PASS→
  available, WARN→degraded, FAIL→missing); else `shutil.which(tool)`
  found → available (detail: probed directly, absent from this type's
  capability set); else probe EVIDENCE file present (evidence/die.json
  / evidence/apkid.json parseable) → available (detail: evidence
  present); else missing (detail: not found, no evidence). Tier stays
  WARN for every record. Downstream disclosure: `promise.prescan.*.state`
  strings ride Part A's `probe_outputs.prescan_state` feature field —
  the vocabulary drops `not_probed` (replaced by the direct-fact
  chain), so future mined tables differ from historical ones on this
  field; disclosed, no migration (the #no-backcompat policy).
  (b) the fixed first-claim probe obligation
  (`prescan_obligation` + `OBLIGATION` + `NATIVE_OBLIGATION_LANES`) —
  flag-gated: flag OFF keeps today's lane-aware memo byte-identical
  (status quo, the A/B's policy A); flag ON replaces it with the
  probes-as-arms note carrying the prior-ranked arm order. Full
  deletion of the fixed-obligation code completes at flag-flip (owner
  decision after the A/B), per the inert-landing discipline.
- ADJACENT PROSE, KEPT AS-IS (review L-note): the toolchain apkid
  item's "apkid recommended … agent to run on first claim" detail
  (toolchain.py:2385) and hypothesis_seeder's apkid-evidence
  competitor-group feed are RECOMMENDATION/evidence faces (the agent
  decides — already arm-shaped posture), not rule tables; they stay.
- REPLACEMENT semantics — probe arms ranked by the prior: die-probe
  and apkid-prescan are ordinary arms (`tools/_INDEX.yaml` entries,
  cost_tier probe/cheap). Ranking rule (deterministic, documented, no
  fitted constants): with no instance features (empty token set) every
  token a probe can reveal is unknown, so identification probes carry
  maximal expected information gain and rank ABOVE method arms whose
  priors are the uninformative wide Beta(1,1); a probe whose revealable
  tokens are ALL already present yields zero gain and demotes below
  informative method arms. Revealable-token sets are static per probe
  (die: language/packer/entropy; apkid: packers/obfuscators) and are
  intersected with the CURRENT features' tokens to compute gain =
  (unknown revealable tokens) / (revealable tokens). Ties break by
  gain, then revealable-token count, then name. This is the SATzilla
  cold-start ordering: pay seconds for identification before spending
  minutes on an uninformed act. Concretely: each probe carries a static
  list of revealable token CATEGORIES (token-key prefixes — die:
  lang=, pf:packing, pk:, die:usable, die:packer=; apkid: pk:, ob:,
  pf:obfuscation, apkid:usable); a category is KNOWN when the current
  features carry any token with that prefix; gain = unknown categories
  / total categories (prefix matching, not value matching — a probe
  reveals a VALUE into an open vocabulary, so "known" is the presence
  of any value in that category). Joint arm ordering (deterministic,
  no fitted constants): positive-gain probes above zero-mass
  (uninformative) method arms; informative method arms (nonzero
  feature/family pool mass) above zero-gain probes; ties by score,
  then revealable-category count, then name.

Grep proof obligation (PR body): `grep -rn "project_type's probe set"
scripts/` returns nothing; `grep -rni "probe.set" scripts/` returns
only eval-checker faces (checker probe sets for grading eval families —
a different concept, untouched) and non-gating prose.

## Decision 5: the A/B is a leave-one-run-out Monte-Carlo replay (EX-5)

`experiments/ex5_predict_before_try.py` (EX-5: EX-2/3/4 taken).
Input: a feature table (default: the committed golden fixture table;
`--table` for any mined table — scale-up face). For every mined run
R carrying ≥1 outcome (leave-R-out training pool for both policies):
the replay models R as the environment — each family's true success
probability p_f = its empirical success rate among R's outcomes
(credit>0 or landed ⇒ success; unknown ⇒ excluded), the honest
per-run outcome model. Each MC trial (seeded, N=200/run):

- Policy A (status quo): fixed probe set first (probes are forced
  first-acts — status-quo rule), then the first METHOD act drawn from
  the sampler over the training pool with the feature prior DISABLED
  (flat family anchor, wide Beta(1,1) on unseen families).
- Policy B: probe acts ordered by Decision-4 gain (no features ⇒
  probes first — same first probe act as A; the policies may differ in
  probe ORDER, which does not change success), then the first METHOD
  act drawn with the feature prior ENABLED (R's features vs the
  training pool, flag on).

Metrics: cold-start first-act success rate = fraction of trials whose
first METHOD act sampled success under p_f; oracle PASS rate = per
held-out run, whether the policy's chosen family contains a settled
credit > 0 outcome in R. Reported per run and aggregated, with the
trial counts and seeds in `ex5-results.json` (deterministic rerun =
byte-identical results).

Decision 6 (data honesty): the only table in-repo has 2 usable runs —
the A/B is UNDERPOWERED by construction and its numbers are protocol
demonstration, not activation evidence. The harness itself declares
underpower when the usable-run count < 3 (fewer than the minimum that
could separate two policies on leave-one-run-out without a coin-flip
aggregate; review M5) and the honest reading: any non-decisive delta
ships flag-off. Activation requires a decisive aggregate win (both
metrics) at real table scale — an owner decision on new mined data,
not this change.

## Design review (independent, pre-implementation)

**Process disclosure**: no subagent-dispatch tool was available in this
implementation session (tool surface offered only SendMessage to
existing sessions; none existed). The adversarial review was therefore
executed as a dedicated in-session pass against the exact contracts
the card names — issue-460-feature-mining (proposal/design/spec),
issue-462-kernel-actuation (design D1-D6, especially D3 method_lead /
D5 envelope host), scripts/rlvr/q_cells.py + its test pins, the
intake/toolchain surfaces, and the fixture data — with verdicts graded
by the same severity ladder. This deviation from the 1-independent-
subagent review discipline is disclosed here and in the PR; the
pre-merge code review (tasks 5.1) repeats the disclosure.

Verdict: FAIL → folded. Defects (all folded above BEFORE any test or
code):

- H1 — the spec's leave-instance-out join ("matched by run-identity
  join keys: features' signature hash and run family") was
  unimplementable at the live face (no run identity exists at sample
  time) and self-contradictory with same-hash pooling. Folded:
  exclusion is the REPLAY's explicit `exclude_run`; the live face
  pools all rows (identical-hash history is borrowing, not leakage).
- M1 — `features_from_workspace` cannot supply task_dir (corpus
  pointer lives in run-state, absent live); target_kind would
  silently null. Folded: optional task_dir + documented degrade.
- M2 — pool keys include non-#432 claim-source strings; pollution
  risk unstated. Folded: namespaces note (registry-intersected
  candidates make non-token pools unreachable) + per-sample cost
  bound documented.
- M3 — the prescan direct-fact fallback chain had no pinned mapping;
  the vocabulary change's downstream effect on Part A's prescan_state
  feature field was unstated. Folded: exact mapping pinned + no-
  backcompat disclosure.
- M4 — flag-on would be dead code at the production seam (no call
  site threaded features). Folded: both #462 call sites
  (strategy_store.method_lead, e2e/checkpoints envelope host) thread
  the workspace features + table when the flag is on, fail-open.
- M5 — the underpower criterion ("fewer usable runs than held-out
  families plus two") was arbitrary and uncomputable before the split
  exists. Folded: < 3 usable runs declares underpower in the harness.

L-notes (no code change required, recorded): toolchain/seeder
recommendation prose is already arm-shaped and stays; the grep-proof
scope (eval-family probe sets are a different concept) is pinned in
Decision 4.

## Code-review folds (independent pre-merge review, post-implementation)

In-session adversarial pass over the staged diff (same process
disclosure as the design review: no subagent-dispatch tool existed in
the session). FAIL → folded → PASS:

- MEDIUM — EX-5's environment seeding carried the POLICY in the seed,
  so identical (trial, family) draws saw different env randomness
  under the two policies (an unpaired comparison). Folded: the env
  seed now carries (run, trial, family) only — paired Bernoulli
  streams; the pairing rule is commented at the fold site.
- LOW (test gap) — receipt-level inertness for flag on + table
  present + no candidate-matching rows was unpinned. Folded:
  test_flag_on_without_matching_rows_receipt_stays_identical.
- L-note (accepted, disclosed) — features_from_workspace imports
  feature_mining._features (private face): Part A shipped no public
  extraction API by non-goal; a second consumer is the trigger to
  promote one.
- L-note (accepted) — a truncated README duplicate row briefly
  existed mid-session (edit-prefix accident); verified repaired
  (git diff shows exactly 1 inserted catalog row; grep -c
  rlvr/q_cells.py = 2: the row + the __init__ mention).
