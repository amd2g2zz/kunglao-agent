# Proposal — issue-460-predict-before-try (Part B)

## Why

Issue #460's owner direction reframes anti-thrashing as predict-before-try:
per-instance prediction BEFORE spending an act (the SATzilla /
algorithm-portfolio move). Part A (PR #470) landed the substrate —
`scripts/feature_mining.py` mining `feature-table/1` rows
(instance features → per-act method/outcome tuples). Today the Q-cell
kernel's cold-start method selection is still UNINFORMED: shrinkage
borrows toward family/global pools only, so a brand-new signature starts
at the family mean even when the mined table already says structurally
similar instances behaved very differently. Meanwhile the intake
pipeline (issue #813/#669 faces) still orders probes by a fixed
per-project_type rule table ("layer not in this project_type's probe
set" + the first-claim prescan obligation) instead of by expected
information gain. This card makes cold-start selection INFORMED and
gates it behind a replayed A/B win.

## What changes

- **B1 — feature-conditioned prior on q_cells** (flag-gated): a
  similarity-weighted pool over the mined feature table enters the
  hierarchical shrinkage as a second anchor source
  (`scripts/rlvr/feature_prior.py` new; `scripts/rlvr/q_cells.py` gains
  an optional keyword-only `feature_pool` anchor argument — flag off /
  table absent = bit-identical kernel, the determinism wall untouched).
  Similarity = Jaccard over the canonical feature-token set (design
  Decision 2); borrow weighting under the one SHRINK_CAP (Decision 3).
- **B2 — #669 probe-set gating retirement**: the per-project_type
  probe-list rule in `scripts/intake_promise.py` (the "layer not in
  this project_type's probe set" membership note) is DELETED — prescan
  records direct capability facts (toolchain item, else tool presence,
  else evidence presence), uniform across lanes/types. The fixed
  first-claim probe obligation is replaced BY THE FLAG with prior-ranked
  `cost_tier=probe` arms (die-probe, apkid-prescan): with no instance
  features, identification probes dominate on expected information gain
  (Decision 4). Capability checks (tool presence) and resource-safety
  wrappers (#436 jadx gate) are untouched.
- **B3 — MC replay A/B (EX-5, the activation gate)**:
  `experiments/ex5_predict_before_try.py` + `ex5-results.json` +
  `ex5-predict-before-try.md` — leave-one-run-out Monte-Carlo replay of
  policy A (flat cells + fixed probe set) vs policy B (feature prior +
  probe arms) over the mined feature table; metrics cold-start
  first-act success rate + oracle PASS rate on held-out runs. **No
  activation without a win**: both B1 and B2 land behind
  `KUNGLAO_PREDICT_BEFORE_TRY` (default OFF); a loss or underpowered
  tie ships flag-off with the honest result.
- Tests: `tests/test_feature_prior_460b.py` (new pins incl. bit-exact
  flag-off identity), `tests/test_intake_promise_813.py` updated for
  the retirement; `tests/test_rlvr_bitexact.py` 16/16 stays green with
  zero edits.

## Non-goals

- No change to settlement/scalar/prior modules — the issue-420 wall
  (`tests/test_rlvr_bitexact.py`) pins are never re-minted here.
- No live-data commits: the A/B replays the committed sanitized fixture
  table (the only mined table in-repo); the harness accepts any mined
  table for scale-up.
- No flag flip in this change: activation (default ON) requires the
  A/B win + review approval, recorded in a follow-up.
- #432 vocabulary, #436 resource gates, toolchain capability probes
  (CHECK_SETS), and eval-family "probe sets" (eval_checker's checker
  probes — a different concept) are untouched.
