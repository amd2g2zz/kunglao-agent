# issue-256-fingerprint-wiring — tasks

## 1. RED tests

- [ ] Worker completions record through the real path: two identical
      no-progress `post_check` faces → streak 2 in
      `runs/zero-output-fingerprint.json`
      (`tests/test_fingerprint_wiring_256.py`)
- [ ] The break lands in production telemetry: third identical face →
      exactly one `zero_output_break` row (actor `zero_output_fingerprint`,
      tool attributed, streak in detail)
- [ ] Unclaimed/orchestrator-side Agent completions never record
- [ ] `zerooutput` gate present exactly once in the `pre_check` battery
      (structural pin, #57 precedent)
- [ ] Tripped circuit rejects a real dispatch end-to-end
      (`pre_check` rc 2, `REJECT zerooutput` on stderr)
- [ ] REJECT_FIXES guidance for `zerooutput` names `failure_analysis`
- [ ] Recorder crash → rc 0 + visible stderr WARN (fail-open, not silent)
- [ ] No-op recorder (returns None) → rc 0 + visible stderr WARN
      (detectable, not silently swallowed)

## 2. GREEN

- [ ] `_record_zero_output_fingerprint` helper + `post_check` call site
      (`hooks/worker_budget_sinks.py`)
- [ ] `check_zero_output_circuit` imported and registered as
      `('zerooutput', ...)` after `backtrack` in the checks battery
- [ ] `REJECT_FIXES['zerooutput']` guidance entry
- [ ] `scripts/zero_output_fingerprint.py` posture docstring graduated
      (recorder code paths unchanged)

## 3. Validation

- [x] Targeted: `tests/test_fingerprint_wiring_256.py
      tests/test_zero_output_fingerprint.py tests/test_canary_gates.py
      tests/test_observability_birth_880.py tests/test_plan_first_ownership_239.py
      tests/test_framework_rigidity_57.py` green (`-n 8`)
- [x] Full fast tier (`-m "fast and not docs"`, `-n 8`) green
- [x] `ruff check` on touched files clean
- [x] `comment_hygiene_lint.py` ratchet clean
- [x] `deploy_manifest.py --write` then `--verify` (both touched files are
      registered deploy targets)
- [x] `openspec validate issue-256-fingerprint-wiring` exit 0

## 4. Review round 2 (adversarial BLOCK — .subagent-review/review-256-wiring.md)

- [x] CRITICAL stale-state deadlock: the gate derives belief freshness
      itself (stored belief_hash vs current belief_hash(ws); mismatch =
      stale = pass); REJECT text names the state file; new test
      trip → belief-move → pre_check PASSES
      (`test_stale_state_after_belief_move_passes`, canary stale face)
- [x] HIGH workspace-global reject: gate scoped to the dispatched
      (claim, tool-family) via `cid`/`tools` from pre_check; `tool_family`
      added to the recorder (mcp__server collapse); new tests: other-claim
      passes, same-claim-different-family passes (e2e + canary faces)
- [x] MEDIUM invoked-only scan: `_scan_invoked_tools` word-boundary
      discipline at the recorder; belief-carrier limitation noted in the
      module docstring; mention-only + positive-control tests
- [x] MEDIUM WARN hygiene: rate-limited once per (ws, reason); partial
      recordings report landed/total and the tool where counting stopped
      (no more "did not land" mislabel); rate-limit + partial tests
