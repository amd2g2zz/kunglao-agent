# Tasks — fail-closed-verification-gates (#78)

## 1. Setup

- [x] 1.1 Branch `fix/fail-closed-gates` off `dev` 105f6ff (one issue / one PR / one branch / one worktree)
- [x] 1.2 Baseline: tests/ 392 passed + 6 pre-existing failures (2 acceptance/contract + 4 #77 RED); scripts/ 226 passed (extended env: pyyaml/pytest/capstone/pefile/jsonschema)

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 proposal.md (What/Why/Scope/Acceptance — fail-closed policy for 3 paths)
- [x] 2.2 design.md (D1-D6: gate classification, unavailability semantics, audit receipt, hook snapshot rule, rejected alternatives)
- [x] 2.3 specs/verification-gates/spec.md (ADDED Requirements + 8 scenarios)
- [x] 2.4 tasks.md
- [x] 2.5 `openspec validate fail-closed-verification-gates` PASS

## 3. RED tests (write first, must fail)

- [x] 3.1 `claim_migrator` BLIND-gate ImportError → `(False, BLOCKED...)`, register unchanged, no ledger event
- [x] 3.2 `claim_migrator` contradiction-gate ImportError → refused
- [x] 3.3 `claim_migrator` inference-gate ImportError → refused
- [x] 3.4 `claim_migrator` gate raises (checker exception) → refused, register unchanged
- [x] 3.5 hook: blind_gate unavailable + newly-PROVEN → `(False, ...)` blocked
- [x] 3.6 hook: register unreadable after write (before exists) → `(False, ...)` blocked
- [x] 3.7 verify: disasm checker unavailable (`binary_path` set) → `disasm.ok=False`, overall != VERIFIED, receipt keys present
- [x] 3.8 verify: disasm checker raises → `disasm.ok=False`, error_class recorded
- [x] 3.9 Mutation sweep: PROVEN/VERIFIED never written under any unavailability

## 4. GREEN — scripts/kunglao_record.py

- [x] 4.1 `REQUIRED_FOR_TERMINAL_STATE` gate registry constant
- [x] 4.2 BLIND/contradiction/inference gates: ImportError + Exception → `(False, BLOCKED receipt)`, no `_set_claim_status`

## 5. GREEN — hooks/worker_budget.py

- [x] 5.1 unreadable register (before exists, after None) → block
- [x] 5.2 blind_gate import failure + newly-PROVEN → block with receipt
- [x] 5.3 contradiction/inference gates required (remove optional flags)

## 6. GREEN — scripts/kunglao_verify.py + schemas

- [x] 6.1 disasm gate: ImportError/Exception → `{"ok": false, state, checker, checker_version, error_class, reason}`; overall → UNVERIFIED-WITH-GAP (unless already REJECTED)
- [x] 6.2 schemas/verify-output.json `overall` enum += `UNVERIFIED-WITH-GAP`

## 7. Regression + validation

- [x] 7.1 tests/ full: 392 passed + 6 pre-existing failures unchanged (no new failures)
- [x] 7.2 scripts/ full: 226 passed
- [x] 7.3 `openspec validate fail-closed-verification-gates` PASS

## 8. PR

- [x] 8.1 push branch, `gh pr create --base dev` with RED→GREEN + mutation evidence → PR #84
- [x] 8.2 STOP — no merge, no close, no delete
