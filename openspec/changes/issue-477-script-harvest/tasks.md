# Tasks — issue-477-script-harvest

- [x] openspec change created; `openspec validate --strict` green;
      adversarial design-review subagent run BEFORE any test (verdict
      PASS-with-fixes; 5 HIGH + 8 MEDIUM + 4 LOW findings — all 17
      applied to design.md + the spec deltas with dispositions recorded
      in design.md's review record: run-start scope floor + ledger-
      missing semantics, outcome-bearing reuse predicate, exact-set
      status matching, stage-then-verify, name rule + collision rules,
      whole-body cage + host-emitted rows, declared cwd, input_sha256,
      land_candidate fork disposition, playbook owner-cover, harvest
      counter type-garbage fail-closed, argv-contract reason,
      runs/ verify-script boundary, at-or-after reuse ordering,
      served_in rename, category equality rule, finalize insertion
      point pinned)
- [ ] RED: sweep + discriminator tests (PROVEN-fact citation incl.
      provenance-path / reproduce / body mention, later-reuse signal,
      one-off skip, sample_specific exclusion, stale-mtime skip,
      idempotent re-sweep) — failed pre-implementation
- [ ] RED: budget tests (harvest counters in the shared ledger doc,
      never-loosen clamp, fail-closed corruption, per-run cap,
      distill counters untouched) — failed pre-implementation
- [ ] RED: verification tests (double-run byte-exact pass, digest
      mismatch → archived not landed, rc!=0 → archived, no anchored
      sample → no landing, worker file never mutated) — failed
      pre-implementation
- [ ] GREEN: `scripts/script_harvest.py` engine — sweep,
      discriminator, verification, spine landing (tools-local +
      harvest-manifest/1 + env-version stamp), playbook chain record,
      CLI (--scan/--harvest)
- [ ] RED: audit-vocabulary tests (three words in AUDIT_ACTIONS +
      EMIT_ACTIONS, `harvest` category, 17-field row shape) — failed
      pre-implementation
- [ ] GREEN: e2e/audit.py words + category + emitters;
      event_taxonomy.EMIT_ACTIONS
- [ ] RED: e2e hosting test (finalize sweeps once on a terminal path;
      harvest failure never breaks the harness) + fixture e2e
      (candidate→landed / one-off→skipped / verification-failure→
      archived) — failed pre-implementation
- [ ] GREEN: `_harvest_scripts` finalize step in checkpoints.py
      (fail-open, `_load_repo_module`)
- [ ] Fixture substrate: `tests/fixtures/harvest-477/` (success-traced
      deterministic script + nondeterministic script + PROVEN fact
      fixture)
- [ ] Worker doc + SKILL.md paragraph (post-run harvest face: what
      qualifies, what lands where)
- [ ] Registrations for new files (scripts/README.md row,
      deploy-manifest --write) + hygiene baseline re-mint if flagged
- [ ] Gates: pytest suites green (-n 2), ruff clean, quality_gates
      --quick ALL-PASS, comment_hygiene_lint clean
- [ ] Review gate: independent code-reviewer PASS → evidence
      `.claude/reviews/477-implementation.md` → minted; PR with
      openspec mapping table + fixture evidence + gates
