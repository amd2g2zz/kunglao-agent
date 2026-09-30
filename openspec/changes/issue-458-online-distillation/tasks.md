# Tasks — issue-458-online-distillation

- [x] openspec change created; `openspec validate --strict` green;
      adversarial design-review subagent run (verdict PASS with fixes;
      5 HIGH + 8 MEDIUM + 4 LOW findings) — all 17 findings fixed in
      design.md + the spec deltas (dispositions recorded in
      design.md): engine-minted run identity, anchored-sample oracle
      resolution, faces-direct dispatch (no sampler ride), real
      probe-evidence shapes, per-run hops budget, flock-guarded
      ledger critical section, refusal-row semantics, stale-marker
      scoping, format-unknown dedup token, allowedTools rack
      derivation, oracle_self_declared flag, honest risk statement,
      genuine-miss discriminator, worker-doc pin — zero tests before
      this landed
- [ ] RED: budget-ledger tests (defaults, per-run reset by run_id,
      never-loosen clamp, fail-closed corruption, trigger memory,
      global counters, hop debits) — failed pre-implementation
- [ ] RED: trigger-scan tests (marker parse incl. sample path,
      unknown-format probe failure, no-marker negative pin, malformed
      marker ignored) — failed pre-implementation
- [ ] GREEN: `scripts/online_distill.py` engine — trigger scan +
      budget ledger (atomic writes, the D2 semantics)
- [ ] RED: report-validation tests (relibrary ref existence, web
      URL+date shape, ≥1 method, depth-1/breadth-3/hop-budget caps,
      whole-report rejection) — failed pre-implementation
- [ ] GREEN: report validator + caps algebra in the engine
- [ ] RED: sample-as-oracle tests (real-bytes execution, engine
      sample-path injection + workspace path guard, satisfied vs
      unsatisfied vs timeout outcomes) — failed pre-implementation
- [ ] GREEN: oracle runner in the engine (bounded subprocess,
      outcome recording)
- [ ] RED: landing-tier tests (tools-local landing + manifest
      provenance, candidate_landed row, no-runtime-global-write
      static pin) — failed pre-implementation
- [ ] GREEN: tier-1 landing face + manifest writer
- [ ] RED: audit-vocabulary tests (three words in AUDIT_ACTIONS +
      EMIT_ACTIONS, distill category, 17-field row shape,
      exactly-one guarantees) — failed pre-implementation
- [ ] GREEN: `scripts/e2e/audit.py` vocabulary + category +
      convenience emitters; `scripts/event_taxonomy.py` words
- [ ] Fixture substrate: `tests/fixtures/distill-458/` generator +
      sample + expected digest; the genuine-miss pin (no registered
      crypto algorithm decodes it); the re-library methodology card +
      index registrations
- [ ] RED: fixture e2e (dry mode) — miss → trigger → budgeted act →
      validated report → satisfied oracle → run-local landing →
      complete audit trail + ledger state — failed pre-implementation
- [ ] GREEN: e2e wiring (`_maybe_distill` tick step; dry-face
      distill responder with a REAL parameter-recovery candidate) +
      loop-integration negative pin (no marker → no distill act)
- [ ] Production face: round_closure SubagentStop trigger scan +
      trigger row + `runs/distill-trigger.json` stamp, fail-open
      pinned; worker doc tools-local line + SKILL.md distill
      dispatch protocol paragraph
- [ ] Three registrations for new files (README / ext-scan /
      deploy-manifest --write, in order) + re-library index
      registration for the card
- [ ] Gates: pytest suites green, ruff clean, quality_gates --quick,
      comment_hygiene_lint clean; paired re-mint when comments land
- [ ] Review gate: independent code-reviewer PASS → evidence
      `.claude/reviews/458-*.md` → mint; PR with openspec mapping
      table + fixture evidence + budget-cap proof
