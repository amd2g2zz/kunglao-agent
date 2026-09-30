# tasks — issue-460-predict-before-try (Part B)

## 1. Gate 1 — spec first

- [x] 1.1 openspec change `issue-460-predict-before-try` (proposal,
      design, tasks, specs/predict-before-try/spec.md);
      `openspec validate issue-460-predict-before-try --strict` green.
- [x] 1.2 Adversarial design review against the existing
      changes/specs — especially issue-460-feature-mining (the
      substrate contract) and issue-462-kernel-actuation (the
      fold/sampler semantics whose pool source this changes).
      Process deviation disclosed: no subagent-dispatch tool existed
      in the session; the review ran as a dedicated in-session
      adversarial pass (see design.md "Design review"). Verdict FAIL →
      folded: 1 HIGH (leave-instance-out join unimplementable at the
      live face → explicit exclude_run replay split), 5 MEDIUM
      (task_dir degrade, pool-namespace pollution note, prescan
      mapping pinned + downstream disclosure, production-seam wiring
      through both #462 call sites, underpower criterion < 3 usable
      runs), L-notes recorded. Zero tests existed before the fold.
      Re-validated --strict green after folding.

## 2. RED (TDD — tests from the spec scenarios)

- [x] 2.1 tests/test_feature_prior_460b.py — flag/inertness: default
      flag off; flag on without table = flag-off identical; receipt
      identity pins (byte-identical sampler output; also flag on +
      table + no matching rows).
- [x] 2.2 similarity pins: identical → 1.0; disjoint → 0.0; empty
      union → 0.0; degraded evidence (null/absent fields emit no
      tokens) lowers but never fabricates opposition; deterministic.
- [x] 2.3 pool pins: similarity-weighted masses incl. credit/act_result
      mapping with unknown excluded; explicit exclude_run (own run
      excluded, other rows pool); anchor tilt strictly higher with a
      successful similar pool; SHRINK_CAP bounds the total anchor
      (alpha+beta = 2 + cap); flag-off/zero-pool bit-exact posterior
      identity (no-pool path = the old formula's exact fractions).
- [x] 2.4 probe-arm ranking pins: cold start (empty tokens) → probes
      above method arms; all-known categories → gain 0.0, demoted
      below informative methods; deterministic pure-function ordering
      + tie-breaks.
- [x] 2.5 B2 pins: prescan records BOTH tools' capability facts on
      every type (no per-type note, no missing key — direct presence
      fallback chain); flag off → obligation memo status quo; flag on
      → probes-as-arms note with the prior's ranked order; updated
      test_intake_promise_813.py retirement scenarios (not_probed
      vocabulary retired; host-independence via injected _which_tool).
- [x] 2.6 bit-exact wall: test_rlvr_bitexact.py 16/16 green, zero
      edits (46 passed alongside test_q_cells_429).

## 3. GREEN

- [x] 3.1 scripts/rlvr/feature_prior.py — flag face, token
      projection (decomposed helpers, ruff C901 clean), Jaccard,
      table loader (feature_mining.validate_row reuse), pool_for with
      explicit exclude_run, features_from_workspace (extraction
      reuse, task_dir optional, fail-open {}), probe-arm
      gain/ranking, PROBE_ARMS categories.
- [x] 3.2 scripts/rlvr/q_cells.py — cell_posterior keyword-only
      feature_pool anchor argument (None/zero-mass = bit-identical);
      sample_method_family keyword-only features/feature_table
      pass-through (flag-gated via _feature_pools, fail-open);
      additive receipt block (rows > 0 only).
- [x] 3.3 scripts/intake_promise.py — per-project_type probe-list
      note deleted (uniform direct-fact prescan chain: report item >
      host presence > evidence presence > missing); flag-gated
      obligation→arms note (fail-open to the legacy memo).
- [x] 3.4 experiments/ex5_predict_before_try.py + ex5-results.json +
      ex5-predict-before-try.md — leave-one-run-out MC A/B (paired
      env seeds after review fold), deterministic (byte-identical
      reruns), honest result: UNDERPOWERED (2 usable runs, 0/0 both
      policies), flag stays off, disclosed prominently.

## 4. Registrations + gates

- [x] 4.1 scripts/README.md catalog row for rlvr/feature_prior.py.
- [x] 4.2 deploy_manifest.py --write + --verify OK (514 entries;
      ext-scan not required for a package module — doc-sync gate 7
      ALL-PASS confirms the registration set).
- [x] 4.3 Gates with real output: new suite (32) + q_cells (30) +
      intake-promise (13) + bitexact wall (16/16) + consumer batches
      (193 + 153 passed/1 skipped, uv -n 4), ruff clean on all 9
      changed code files, devkit/quality_gates.py --quick ALL-PASS,
      gate 7 ALL-PASS, comment_hygiene_lint clean (871 files) —
      paired re-mint held (--emit → deploy --write → mint → commit).
- [x] 4.4 Grep proof: `grep -rn "project_type's probe set" scripts/
      tools/ hooks/ agents/ devkit/ skills/` → 0 matches; "probe set"
      survives only in scripts/eval_*.py (eval-checker family grading
      probes — different concept, untouched, disclosed).

## 5. Review gate + ship

- [x] 5.1 Code review (in-session adversarial pass over the staged
      diff — process deviation disclosed: no subagent-dispatch tool
      in the session; same severity ladder): FAIL round (1 MEDIUM:
      EX-5 env seeding was policy-dependent → folded to paired seeds;
      1 LOW test gap: receipt-level no-matching-rows inertness →
      pinned) → PASS → evidence .claude/reviews/460b-predict-before-
      try.md → review_gate.py mint OK (reviewer-460b-in-session).
- [ ] 5.2 PR to dev ("feat: #460 Part B — feature-conditioned prior
      (flag-gated) + #669 retirement + MC A/B") with openspec mapping
      table, A/B results (win or honest loss), flag-off proof, #669
      grep proof, gates output; CI five legs green (GnuTLS flake →
      rerun --failed; never merge red); merge; do NOT close #460 if
      shipping flag-off pending a win.
