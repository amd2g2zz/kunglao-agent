# tasks — issue-438-minor-tail

- [x] 1. RED tests first:
      tests/test_round_credit_alignment_433.py — undecodable register
      (question_claims degrades to set(), fact_artifacts completes,
      answers_question false) + the declaration pin re-minted to
      stage_milestone NOT in legs;
      tests/test_round_credit_cited_cap_438.py — README row names the
      admission-ticket/value-condition ladder, the cited cap,
      CITED_CAP_DEFAULT with its value, and cited_over_cap. RED
      confirmed (decode error raised; leg still declared; row still
      v2).
- [x] 2. Implement decode tolerance: UnicodeDecodeError joins the
      question_claims except tuple; docstring names the undecodable
      case (scripts/rlvr/scalar.py).
- [x] 3. Remove the stage_milestone leg from
      references/contracts/reward-rules.yaml and reword the
      value_ladder note's milestone sentence to the disclosed
      mechanism (enters through the cited/used-toward-stage leg;
      unlinked settles the exploration-option trace).
- [x] 3b. Design-review defect 1: reword the code-side FIRST-MATCH
      ladder comment (scripts/rlvr/scalar.py) and the 433 test module
      docstring to state the mechanism instead of enumerating a
      declared stage-milestone arm.
- [x] 4. Rewrite the scripts/README.md scalar_settlement.py row's
      LEVEL 2 round-credit fragment to the v3 ladder + cap (pin
      derives the cap value from the module — defect 3).
- [x] 5. Gates green: the round-credit / scalar / reward suites
      (197 passed) + docs gates (101 passed), ruff clean on changed
      files, devkit/quality_gates.py --quick ALL-PASS,
      comment_hygiene_lint clean (861 files, no new debt), openspec
      validate --strict valid, deploy_manifest.py --write re-minted
      (the two changed tracked files' sha256 rows; --verify green —
      CI's slow tier caught the first push without it).
- [x] 6a. Review gate: independent code-reviewer PASS on the staged
      diff (decode-tolerance correctness, leg-removal consumer sweep,
      contract-honesty cross-check, test quality, hygiene, scope;
      suites re-run independently) -> evidence file ->
      review_gate.py mint.
- [ ] 6b. PR with the Requirement -> implementation -> test mapping
      table; CI green; merge; close issue 438.
