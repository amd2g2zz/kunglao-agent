# tasks — issue-461-attribution-state (Phase 1)

- [x] 1. RED tests first: tests/test_rlvr_obstacles_461.py (schema,
      validation, record mint/order, tolerant read, face digest, the
      three canonical failure-signature fixtures with expected rows);
      re-pin + extend tests/test_state_signature_396.py (ob= segment);
      extend tests/test_experience_freeze_396.py (recording wall);
      tests/test_ex4_attribution_trap_461.py (determinism + expected
      sequence). RED confirmed against dev.
- [x] 2. Implement scripts/rlvr/obstacles.py (KINDS, validate,
      record, read, face, CLI) + rlvr/__init__ export map.
- [x] 3. Extend scripts/rlvr/state.py: obstacles face in snapshot,
      ob= signature segment, docstring row; state_signature shim
      gains the obstacle_face re-export.
- [x] 4. Worker protocol: agents/kunglao-worker.md intervention
      subsection under Failure report protocol (no tracker tokens, no
      dates).
- [x] 5. EX-4: experiments/ex4_attribution_trap.py + ex4-results.json
      + ex4-attribution-trap.md (declared synthetic; the Phase-2
      training shape).
- [x] 6. Registration: scripts/README.md row, scripts/rlvr/README.md
      face map + package tree, tests/_tiers.py fast set, deploy-manifest
      re-mint (deploy_manifest.py --write; --verify OK 510 entries).
- [x] 7. Gates: pytest new+touched (-n 4, 127 passed incl. deploy
      lifecycle), ruff clean, devkit/quality_gates.py --quick ALL-PASS,
      comment_hygiene_lint.py clean.
- [x] 8. Review gate: independent code-reviewer round 1 FAIL (3 HIGH
      / 1 MEDIUM / 1 LOW — stale manifest sha, CLI bootstrap crash on
      the documented invocation, freeze-wall import-form hole,
      short-write raise path, rc marker drift) -> all five fixed ->
      round 2 PASS; .claude/reviews/461p1-attribution-state-pass.md
      evidence; review_gate.py mint OK; subagent-review JSON (Gate 5).
- [ ] 9. Ship: push feat/attribution-state-461-p1, PR to dev with the
      openspec mapping table, gates, Phase-2 out-of-scope disclosure;
      CI five legs green; merge. Do NOT close issue 461.
