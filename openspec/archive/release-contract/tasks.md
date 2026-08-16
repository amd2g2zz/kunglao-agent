# Tasks — release-contract

- [x] 1. OpenSpec scaffolded (`openspec new change release-contract`)
- [x] 2. proposal.md / design.md / specs/release-contract/spec.md written
- [x] 3. `openspec validate release-contract` prints valid
- [x] 4. RED: tests/test_release_receipt.py (manifest honesty / receipt shape / CLI inventory / README reconciliation / no-secrets) — failing
- [x] 5. GREEN: pyproject.toml + `uv lock` (uv.lock committed; pytest in PEP 735 dev group so `uv sync --locked` installs it)
- [x] 6. GREEN: vendor agents/ (10 definitions) + release-manifest.yaml
- [x] 7. GREEN: scripts/release_receipt.py (--check / --pytest-junit / --manifest / --out / --revision / --no-tests) + schemas/release-receipt.json
- [x] 8. GREEN: kunglao.py registers verify + record (router surface decide/tick/verify/record/health)
- [x] 9. GREEN: .github/workflows/release-check.yml replaces python-package.yml; .gitignore += .venv/ /release-receipt.json
- [x] 10. GREEN: README reconciliation (badge, install command, CLI reference note, receipt-linked status)
- [x] 11. Full suite: 6 pre-existing failures UNCHANGED (630 passed / 6 failed / 1 skipped), all 12 new tests green; `uv sync --locked` + eval oracle selfcheck clean
- [x] 12. Push chore/release-contract (origin) + PR #86 → dev (NOT merged — orchestrator verifies first)
