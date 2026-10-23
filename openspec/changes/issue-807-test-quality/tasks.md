# Tasks — #807 test quality rail

Order pinned: floor must never light up red before the cleanup lands.

1. [x] SDD: proposal / spec / tasks (this change dir), invariants cited.
2. [x] `scripts/test_inventory.py` — AST classifier, per-class counts; run
       over tests/; commit inventory output (devkit/reports/).
3. [x] De-bloat: verified deletions only; per-file justification; each removal
       names the inheriting test; net function delta DOWN; belt green after.
4. [x] Baseline: `uv run pytest -m "not fast" -n 4 --cov=scripts --cov=hooks
       --cov-report=json:coverage.json` → record measured % (before floor).
5. [x] Floor (TDD): RED-first `tests/test_coverage_floor_ratchet_807.py`
       (monotone comparator units + file schema + target pin) → implement
       `scripts/coverage_floor.py` + `coverage-floor.json` → CI steps in
       release-check.yml → amend `tests/test_coverage_policy_564.py` + policy
       comments (pytest.ini / pyproject.toml / release-check.yml).
       DEVIATION (recorded for owner): measured baseline is 58.59%, not
       >= 70; the ratchet is seeded at truth (floor 57.0 = baseline minus
       cross-platform tolerance, hygiene-baseline precedent) with
       min_floor = 70.0 as the immutable climb target; floor >= 70 from
       day one would land CI red with no raise path inside this card.
6. [x] Registration triple: scripts/README.md rows → `tools/ext-scan.py`
       regenerate → `scripts/deploy_manifest.py --write` LAST.
7. [x] Gates: `uv run python devkit/quality_gates.py --quick` ALL-PASS;
       `uv run pytest -m "fast and not docs" -q -n 4` green; openspec validate.
8. [x] Review-gate chain per logical commit; push; PR → dev (no merge).
