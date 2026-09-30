# tasks — issue-461-option-death (Phase 2)

- [x] 1. Adversarial design review (read-only architect subagent) vs
      the four mandated decisions + adjacent contracts; defects fixed
      in design.md BEFORE any test (round 1 FAIL: 11 defects — 2 HIGH
      (Phase-1 spec contradiction, envelope host unwired), 4 MEDIUM, 5
      LOW — all fixed: Phase-1 recording-only clause amended in its
      still-open change with the Phase-2 carve-out; BOTH sampler hosts
      wired; zero-registry {} verdicts; aging asymmetry disclosed;
      family-global floor disclosed; EX-6 fidelity + ts determinism;
      round 2 re-verification: PASS, no new defects). `openspec
      validate --strict` green on both changes.
- [x] 2. RED tests first: tests/test_rlvr_termination_461.py
      (posterior form: counts/pins, different-causes, threshold at 2,
      revival arithmetic, cause-free no-op, fail-open reads; decision
      face: state conditioning, zero-registry {} rule, no-cells never
      dead, constants; sampler: floor application, byte identity
      absent verdicts, import wall, both-host fail-open + envelope
      host source-shape pin); tests/test_ex6_option_death_461.py
      (determinism + expectations). RED confirmed against dev.
- [x] 3. Implement scripts/rlvr/termination.py (report / verdicts /
      option_dead / CLI; lazy imports; fail-open reads; verdicts {}
      at zero registry) + rlvr/__init__ export map + the one-line
      Phase-2 note in obstacles.py's docstring.
- [x] 4. Wire the sampler: q_cells.sample_method_family death kwarg
      (duck-typed verdict, floor multiplier, additive receipt block,
      byte-identical absent); BOTH hosts thread verdicts fail-open —
      strategy_store.method_lead AND
      e2e/checkpoints._sample_envelope_family (the action-selection
      site).
- [x] 5. EX-6: experiments/ex6_option_death.py + ex6-results.json +
      ex6-option-death.md (declared synthetic; the issue-acceptance
      A/B/C on the EX-4 trap trajectory; deterministic).
- [x] 6. Registration: scripts/README.md row, scripts/rlvr/README.md
      face map + package tree, tests/_tiers.py fast set, ext-scan +
      deploy-manifest re-mint (deploy_manifest.py --write; --verify).
- [x] 7. Gates with real output: pytest new+touched (-n 4) —
      82 (termination + EX-6 + bitexact + obstacles + ex4 + state-sig
      + freeze) + 158 (q_cells + compose + freeze + signature +
      feature-prior) + 82 (e2e runner) all green; the bit-exact wall
      16/16 with ZERO edits (no diff on the file); ruff clean on every
      changed file (scripts/-wide baseline noise is pre-existing on
      untouched files); devkit/quality_gates.py --quick ALL-PASS;
      comment_hygiene_lint clean after the paired re-mint
      (--emit-baseline, ext-scan, deploy_manifest --write 515 entries,
      --verify OK).
- [x] 8. Review gate: independent code-reviewer subagent → round 1
      FAIL (1 CRITICAL: stale deploy-manifest sha for termination.py —
      post-mint docstring edit; 1 MEDIUM: vacuous or-True assert; 2
      LOW: dead replay() param, unpinned alive-verdict block presence)
      → all four fixed → round 2 PASS (reviewer's own runs: 48 passed
      incl. bitexact 16/16 zero-diff, ruff clean, manifest verify OK,
      EX-6 results re-verified byte-identical) → evidence
      .claude/reviews/461p2-option-death-pass.md (reviewer-461p2) →
      review_gate.py mint OK.
- [x] 9. Ship: push feat/option-death-461p2, PR to dev (openspec
      mapping table, EX-6 results, gates), CI five legs green,
      `gh pr merge --merge`; comment on #461 summarizing P1+P2; CLOSE
      #461 (both phases delivered).
