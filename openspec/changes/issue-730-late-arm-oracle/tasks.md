# tasks — issue-730-late-arm-oracle

## 1. The RED contract

- [x] `tests/test_late_arm_oracle_730.py`: eight pins —
      late-armed case observes an already-settled claim (the defect);
      a REFUTED claim banks failure mass; pre-arm ordering keeps its
      existing behaviour and the amendment that follows is a no-op;
      the amendment is idempotent (no new rows, no moved parameters);
      mixed ordering observes each claim exactly once; observation rows
      are auditable (case_id/claim_id/passed/source); no fabricated
      bucket (no question / unarmed question / non-decisive terminal);
      an unarmed (thin) case carries no observation
- [x] confirmed RED before implementing (8 failed, `AttributeError`)

## 2. The dedup record + the amendment

- [x] `scripts/settle_round_credit.py`: `CASE_OBS_SCHEMA`
      (`case-observation/1`), `_observed_pairs()` (the dedup set, folded
      from the ledger's own rows), `_apply_case_observations()` (the one
      write face: rows then closed-form posterior updates, fail-open)
- [x] `record_case_settlements()` re-pointed at the shared write face;
      signature, return keys and its arming-blind / non-deduped contract
      unchanged
- [x] `amend_case_settlements(ws)` — the late-arm sweep over
      decisive-terminal claims against ARMED cases, pair-deduplicated
- [x] `run()`: fresh leg first, amendment second (order load-bearing —
      commented at the call site); `case_observations` reports the total
      with `case_observations_late_arm` alongside

## 3. Schema registration

- [x] `rlvr/consolidated_ledger.py`: `NATIVE_SCHEMAS` (schemas born in
      the consolidated file, no legacy rel to derive them from) folded
      into `REGISTERED`, so `liveness()` pre-seeds
      `experience:case-observation/1` at 0 — a dead writer reads DEAD,
      never absent

## 4. Docs + registries

- [x] module docstring: the two-leg invariant and the load-bearing order
- [x] `scripts/README.md` catalog row updated to the current behaviour
      (docs-contract)
- [x] lints: formal-code clean (no tracker references stay in
      production comments), comment-hygiene baseline gains the new test
      file's entry (diff-verified: exactly one entry added, no other
      ratchet moved), silent-except clean
- [x] `openspec validate issue-730-late-arm-oracle` exit 0

## 5. Review round — findings and fixes

Both review slices returned FAIL. The defects they proved, and what
changed:

- [x] **Dedup lived in entry construction, not the write face.** Broke
      within a pass (two docs sharing a case id -> 2 rows, alpha 3.0) and
      ACROSS passes (a settle-path retry re-banks a claim an earlier
      amendment already observed -> alpha 2.0 -> 3.0, no error field).
      Fixed: one entry builder that extends the dedup set as it builds,
      and BOTH legs consult the ledger.
- [x] **A refused `append()` counted as an observation.** `append`
      returns False rather than raising; the result was ignored, so with
      an unwritable ledger the pass re-observed every tick behind a
      healthy-looking count. Fixed: count rows that actually landed and
      set the error field on a shortfall.
- [x] **Rows were written before the posterior.** A failed posterior save
      left the pair reading as observed forever while the belief never
      moved — the permanent silent gap this card exists to close. Fixed:
      belief first; the opposite failure costs at most one
      re-observation and self-heals.
- [x] **The spec's unarmed-case claim was false** (the fresh leg was
      arming-blind). Fixed by tightening the code, not by weakening the
      spec: both legs now observe only armed cases.
- [x] **`run()` dropped the amendment's error field** — a broken
      amendment read as "nothing to do" in the mechanism's `--json`
      readout. Fixed: either leg's error propagates.
- [x] **The pass ordering had no test** (swapping the legs still passed
      8/8), nor did the liveness key. Fixed: `run()` end-to-end,
      cross-pass retry, duplicate case id, refused-append, unarmed-case
      and liveness pins added.
- [x] removed the now-orphaned `_linked_case_ids` (superseded by the
      single-scan index)

## 5b. Review round 2 — findings and fixes

The contract slice returned FAIL; the implementation slice PASSed with
two non-blocking residuals. What changed:

- [x] **A missed suite**: `tests/test_credit_settle_634.py` — this
      module's OWN original suite — went red under the armed-only
      tightening (3/11), and the round-1 verification list omitted it.
      Fixed by REVERTING the tightening on the fresh leg, not by editing
      that suite: it is the module's original contract, and the change is
      unrelated to the late-arm gap. The link index now takes an
      `armed_only` flag (amendment true, fresh false) and the asymmetry is
      documented in the spec, the design and the code.
- [x] **The ordering pin had no teeth** — the round-1 `run()` test only
      exercised the late-arm ordering, where `banked` is empty, so
      swapping the legs still passed. Fixed:
      `test_run_attributes_a_new_settlement_to_the_fresh_leg` asserts the
      fresh leg's `source`, and a leg-swap mutation now fails 2 tests
      (verified by probe, then reverted).
- [x] **The error propagation was fixed but unpinned**. Fixed: a pin that
      forces the amendment's row append to be refused and asserts the
      error reaches the pass result.
- [x] **A docstring overstated a property the probes disproved.** It
      claimed the belief-first failure was "bounded and self-healing"; a
      persistent refusal in fact drifts without bound. Fixed: the
      docstring now states both windows honestly and says why the error
      field is set on every shortfall.

## 6. Verification

- [x] unit: 15 pins in `tests/test_late_arm_oracle_730.py`; 54 passed
      across the affected suites (`test_late_arm_oracle_730`,
      `test_credit_settle_634`, `test_reward_source_678`,
      `test_rl_output_path_691`, `test_ledger_consolidation_721`)
- [x] `tests/test_rl_output_path_691.py` updated faithfully: it observed
      ONE claim `_K` times, which is the double-count the invariant
      forbids; it now settles `_K` DISTINCT claims per side and its
      assertions are unchanged (independently judged faithful by review)
- [x] mutation probes: a leg swap fails the ordering pins; removing the
      arming filter fails the unarmed pin; removing `NATIVE_SCHEMAS`
      fails the liveness pin
- [x] docs-marked suite: 143 passed, 1 skipped
- [x] end-to-end on real workspace data (scratch copy — live untouched):
      the pass recorded 3 observations (`C-005` pass on q2, `C-009` fail
      on q2, `C-018` fail on q1), created `runs/posteriors.yaml` with
      `case-q2-param-generation` at `alpha 2 / beta 2` and
      `case-q1-trigger-chain` at `alpha 1 / beta 2`
- [x] idempotence on the same real data: second pass recorded 0, row
      count stayed 3, posterior parameters unchanged
