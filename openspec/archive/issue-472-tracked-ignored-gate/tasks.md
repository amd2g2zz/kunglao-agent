# Tasks — tracked-vs-ignored mechanical gate (#472)

## 1. Investigation

- [x] 1.1 Confirm tracked-but-ignored set on dev 8e85dfa: 2 process artifacts
      (`.review/baseline-failures.txt`, `.review/final-failures.txt`) + 5 golden
      fixtures (`F-03/F-06 ws/runs/worker-status-*.md`, matched by bare `runs/`
      rule at depth)
- [x] 1.2 Confirm `git check-ignore` index-awareness: default flags exit 1 on
      tracked-but-ignored paths; `--no-index` required for truthful detection
- [x] 1.3 Confirm no consumer references the two `.review/*.txt` artifacts
      (grep tests/ scripts/ hooks/ — zero hits)

## 2. SDD

- [x] 2.1 proposal.md (why / what / impact, references #472)
- [x] 2.2 tasks.md (this file)

## 3. TDD

- [x] 3.1 RED: write `tests/test_no_tracked_ignored_files.py` (global
      ls-files × check-ignore --no-index --stdin gate + allowlist + allowlist
      hygiene assertion)
- [x] 3.2 RED witness: `git add -f` a fresh ignored file (`.review/tmp.txt`)
      → run test → FAIL listing the file → `git reset` (not committed)
- [x] 3.3 GREEN: P1 `git rm --cached` the two `.review/*.txt` artifacts →
      test PASSes with the 4-entry golden allowlist

## 4. Validation

- [x] 4.1 Target run: `uv run python -m pytest -q tests/test_no_tracked_ignored_files.py`
- [x] 4.2 Full suite: `uv run python -m pytest -q -m "not load_sensitive"`
- [x] 4.3 `uv run python scripts/release_receipt.py --check`
- [x] 4.4 Commit, push, PR → dev; body carries RED witness + acceptance
      checklist; do not merge
