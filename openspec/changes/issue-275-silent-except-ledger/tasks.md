# tasks — issue-275-silent-except-ledger

- [x] 1. Detector: AST rule in scripts/silent_except_lint.py
      (no-op-body except handlers: `pass`/`...`/bare-string Constant
      bodies, no raise, no trace call; scripts/ + hooks/ scan roots;
      fail-closed on syntax/unreadable files).
- [x] 2. Ratchet: load_baseline/compare/emit_baseline mirroring
      hygiene_baseline semantics (increase / cleared-entry /
      loose-entry / stale-entry / unbaselined / no-baseline).
- [x] 3. Baseline seeded via the tool's own `--emit-baseline`:
      scripts/silent_except_baseline.yaml (199 silent handlers, 83
      files; calibrated to the issue's per-file evidence).
- [x] 4. Tests RED-first: tests/test_silent_except_lint.py — 32 tests
      (detector shapes incl. comment-documented silence still counted,
      TryStar, nesting, out-of-scope shapes; ratchet increase/clear/
      loose/stale/unbaselined/no-baseline; CLI emit determinism,
      emit-refusal, json shape, baseline override, subprocess exit
      codes; real-tree self-scan gate). RED run confirmed
      (ModuleNotFoundError) before implementation.
- [x] 5. CI: silent-except step appended to the lint-hygiene job in
      .github/workflows/release-check.yml (no new CI leg; static
      command, no event-context interpolation).
- [x] 6. Registration: scripts/README.md catalog row (Release & CI
      support table); deploy-manifest regenerated via
      `deploy_manifest.py --write` (399 entries) and `--verify` green;
      tools/_INDEX.ext.yaml row via ext-scan.
- [x] 7. Quality-gates ruling: NOT registered as a new gate number —
      extending lint-hygiene is the smallest surface and avoids the
      gate-count doc-sync ripple (documented in proposal + design).
- [x] 8. Sibling gates green: comment_hygiene_lint clean from root
      (tracker-ref patterns stripped from the new .py files),
      release_check_selfcheck green, ext-scan green.
- [ ] 9. Batches 2-3 (NOT this change): top-4 offender files
      (convergence_check 10, statusline_snapshot 10, backtrack_loop 9,
      heartbeat_tick 9 — 38 sites) as one lane; remaining ~161 sites
      in file-family batches; each site: emit / null_reasons /
      rate-limited WARN per the policy.
