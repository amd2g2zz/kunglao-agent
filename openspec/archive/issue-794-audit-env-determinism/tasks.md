# Tasks — issue-794-audit-env-determinism

## 1. SDD

- [x] 1.1 proposal.md (attribution summary + test-side-only scope)
- [x] 1.2 design.md (inherit-minus-behavioral decision, whitelist procedure, sweep table)
- [x] 1.3 tasks.md

## 2. RED pin (one commit before any seam change)

- [x] 2.1 `tests/test_audit_env_determinism_794.py` — pin A: flag scrub
      (echo probe under `env={FLAG: "1"}` + empty-bins behavioral pin)
- [x] 2.2 pin B: UTF-8 injection (`PYTHONUTF8`/`PYTHONIOENCODING`), setdefault
      override contract, capture-side latin-1 survival
- [x] 2.3 RED evidence: 5 failed, 1 passed clean (the pass = override-contract
      pin, green by design both phases); polluted duo baseline 2 failed

## 3. GREEN

- [x] 3.1 `_run_cli` scrub `_BEHAVIORAL_ENV_VARS` after `env=` merge
- [x] 3.2 `_run_cli` `setdefault` PYTHONUTF8=1 / PYTHONIOENCODING=utf-8
- [x] 3.3 `_run_cli` `encoding="utf-8", errors="replace"` (shape preserved)
- [x] 3.4 GREEN evidence: clean 20P/1S both files; polluted 14P/1S (was 2F)

## 4. Sweep

- [x] 4.1 `grep -rn "dict(os.environ)" tests/` sweep — verdicts in design.md table
- [x] 4.2 same-batch: `test_exit4_no_repair_e2e.py::_run` — RED polluted 1F/6P →
      GREEN 7P both environments

## 5. Validation

- [x] 5.1 clean trio: 27 passed, 1 skipped
- [x] 5.2 polluted: 14 passed, 1 skipped on the audit file (the point of the fix)
- [x] 5.3 full suite in worktree: 4516 tests, 2 failed — both pre-existing
      machine-local (adb device attached to this host), reproduced identically
      on pristine origin/dev 225005d, zero coupling to this branch (evidence
      table in design.md)
- [x] 5.4 quality gates: Gates 1,3,4,5,6,7 PASS; Gate 2 blocked only by the two
      machine-local reds above (CI is authoritative)
- [x] 5.5 `scripts/release_receipt.py --check` exit 0
- [x] 5.6 `ruff check .` All checks passed

## 6. Ship

- [x] 6.1 review-gate evidence per commit + PR `fix/794-audit-env-determinism` → dev
- [ ] 6.2 Windows-native rerun of the duo remains a user-side follow-up
      (CI + macOS dual-environment already proven; noted in PR body)
