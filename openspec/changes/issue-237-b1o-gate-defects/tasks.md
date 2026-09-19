# tasks — issue-237-b1o-gate-defects

## 1. RED (TDD)

- [x] 1.1 tests/test_plan_drift_237_d1_d3.py — D1 RED: OPEN chain answering
      q1's sub-questions -> UNANSWERED_QUESTION must NOT fire (fails pre-fix).
- [x] 1.2 D1 RED: lone OPEN answering claim -> no drift; no answerer at all
      -> still fires; terminal answerer -> still answers (regression pins).
- [x] 1.3 D3 RED (adversarial, incident replay): PROVEN claim + credible
      self-written verify record + NO dispatch rows -> UNVERIFIED_EVIDENCE
      still fires.
- [x] 1.4 D3 RED (maker!=checker): self-attested dispatch rows
      (worker:/verifier: actors) do NOT corroborate; wrong-claim hook rows do
      NOT corroborate; missing log fail-closed.
- [x] 1.5 D3 GREEN-path pin: hook-attributed verifier dispatch row + record
      -> no UNVERIFIED_EVIDENCE.
- [x] 1.6 tests/test_dispatch_gate_237_passthrough.py — D2 RED: drift-blocked
      workspace, kunglao-redteam dispatch on the PROVEN claim must NOT be
      blocked (rc 2), kunglao-worker dispatch on the same claim MUST be
      blocked, pass-through leaves a trace row.

## 2. GREEN

- [x] 2.1 scripts/plan_drift_detector.py — D1: `question_progress` +
      cycle-safe `_transitive_ancestors` + `_depends_on_edges`; UNANSWERED_QUESTION
      fires only on `none`.
- [x] 2.2 scripts/plan_drift_detector.py — D3: `_load_dispatch_rows` +
      `_corroborating_dispatch_claims` + `corroborated_verified_ids`; check()
      switches to the corroborated set; `extract_verified_claim_ids` semantics
      untouched (write_gate/#827 pins).
- [x] 2.3 hooks/dispatch_gate.py — D2: `_is_verifier_remediation_dispatch` +
      pass-through branch in `main()` with `drift_verifier_passthrough` trace.
- [x] 2.4 scripts/event_taxonomy.py — register `drift_verifier_passthrough`.
- [x] 2.5 Re-pin tests/test_plan_drift_unverified.py no-drift fixtures with
      corroborating log rows; register new test modules in tests/_tiers.py
      (fast: detector unit file; slow: hook-interaction file).

## 3. Verification

- [x] 3.1 Targeted: drift/827/602/237 test files green.
- [x] 3.2 `uv run python -m pytest -m "fast and not docs" -n auto --dist
      loadgroup -q` — no regressions.
- [x] 3.3 `uv run ruff check` on touched files.
- [x] 3.4 `openspec validate issue-237-b1o-gate-defects` exits 0.

## 4. Adversarial-review fixes (review-237-b1o, BLOCK -> addressed)

- [x] 4.1 H1: agent identity single-sourced in hooks/lib_kunglao.py
      (`resolve_dispatch_agent` + `is_verifier_remediation_dispatch`);
      dispatch_gate delegates both; worker_budget_sinks pre_check uses the
      shared resolver for the #461 row (`row_agent`) — subagent_type-shaped
      verifier dispatches now land `agent=kunglao-redteam`.
- [x] 4.2 H1 (same defect, second face): worker_budget pre_check's own
      `check_plan_drift` gate rejects on any drift rc — verifier-remediation
      dispatches pass through it too, or the honest path dies at the second
      hook and the #461 row can never be written.
- [x] 4.3 H1 loop test: subagent_type-shaped verifier dispatch -> dispatch_gate
      pass-through -> worker_budget pre_check approval (real emitter) -> #461
      row with verifier marker -> record lands -> corroborated_verified_ids
      non-empty -> UNVERIFIED_EVIDENCE clears for the dispatched claim.
      test_plan_drift_unverified.py corroboration rows now written through
      the REAL #461 emitter, not a hardcoded mock format.
- [x] 4.4 H2: design.md D3 rewritten honestly — the hook-attribution pin is
      a process bar, not authenticity (emit actor is free text, emission
      never validated at runtime, runs/ worker-writable; hand-crafted hook:
      rows corroborate); ts/trace authenticity binding extended as follow-up
      on #263 item 2. Detector docstrings de-oversold to match.
