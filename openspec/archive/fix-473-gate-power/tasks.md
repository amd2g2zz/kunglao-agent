# Tasks — gate-chain power-on (#473)

## 1. Investigation (done pre-change)

- [x] 1.1 Confirm zero oracle registration flow: grep task-oracle/task_oracle
      over skills/, hooks/, scripts/ — only the template + completion_gate
      consumer side exist; no writer.
- [x] 1.2 Confirm premature_termination_detect's only consumer is
      scripts/completion_gate.py exit-1 reason folding (guarded on oracle +
      open_items + declaration_text).
- [x] 1.3 Confirm fingerprint blind spots against the 2026-08-18 narration
      (F2 handoff family / F3 time cost / F4 semantic completion all absent).

## 2. SDD

- [x] 2.1 proposal.md (why / what / non-goals / impact)
- [x] 2.2 tasks.md (this file)
- [x] 2.3 specs/gate-chain-power/spec.md (ADDED requirements + scenarios)

## 3. TDD

- [x] 3.1 RED: `tests/test_gate_power_473.py` —
      (a) 4-step escape fixture fires >=3 fingerprints (baseline: 0-1),
      (b) clean completion fires zero (precision guard),
      (c) init leaves a non-empty task-oracle.yaml (baseline: absent),
      (d) imperative + open-claims signals block (baseline: no F5),
      (e) heartbeat tick report carries oracle_registered,
      (f) tool-rebuttal duty: 需人工 declaration carries
          require_evidence tool_search_zero_hit.
- [x] 3.2 RED witness recorded (baseline pytest output in the PR body).
- [x] 3.3 GREEN: fingerprint expansion + F5 + require_evidence in
      premature_termination_detect.py; oracle skeleton write in
      kunglao-init.py; tick oracle_registered field; SKILL.md Phase 1
      backfill step; template header comment.

## 4. Validation

- [x] 4.1 Target: `uv run python -m pytest -q tests/test_gate_power_473.py
      tests/test_premature_termination_detect.py
      tests/test_completion_gate.py tests/test_init_deploy_env.py
      tests/test_heartbeat_tick.py`
- [x] 4.2 Full suite: `uv run python -m pytest -q -m "not load_sensitive"`
- [x] 4.3 `uv run python scripts/release_receipt.py --check`
- [x] 4.4 Leave changes staged; orchestrator commits/PRs after review.
