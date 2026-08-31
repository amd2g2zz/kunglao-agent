## 1. Setup

- [x] 1.1 Worktree `D:/codebase/kunglao-issue-686-write-guard-adjudicate` branch `issue-686-write-guard-adjudicate` off origin/dev (`b2b3661`, post-#685)
- [x] 1.2 Baseline reproduced: `tests/test_write_guard_532.py tests/test_write_guard_supersedes_528.py` → 7 failed / 15 passed, all rc=0 + empty stderr

## 2. Root-cause isolation

- [x] 2.1 In-process driver over the full decision flow (resolve → carrier → post_image → shadow → adjudicate legs): all 7 shapes produce the correct BLOCK on Windows — rule layer NOT dead
- [x] 2.2 Debug child under exact harness env: `sys.stdin.read()` raises `UnicodeDecodeError` (byte 0xa1, GBK em-dash) → `_read_payload` swallows → `{}` → `main()` silent RC_ALLOW
- [x] 2.3 Host locale confirmed `cp936`; Linux hosts utf-8 end-to-end (why CI stayed green)

## 3. OpenSpec artifacts (SDD)

- [x] 3.1 proposal.md (root cause + solution + acceptance)
- [x] 3.2 design.md (D1-D6: decode chain, non-changes, debug channel, test strategy)
- [x] 3.3 specs/write-guard-adjudicate/spec.md
- [x] 3.4 tasks.md

## 4. RED tests (`tests/test_write_guard_686.py`)

- [x] 4.1 7 parametrized must-block cases (R1 self-stamp / W-2 invented status / unresolvable fail-closed / block-emits-kunglao-log / chainless correction / inherited-passes chained / fake-chain N-999)
- [x] 4.2 Allow guards: clean em-dash fact write rc=0; non-carrier write rc=0
- [x] 4.3 RED run recorded verbatim (actual: 8 failed / 2 passed — the 7 must-block cases + the debug-trace channel red; allow guards green) — RED-only commit

## 5. Implementation (GREEN)

- [x] 5.1 `hooks/write_guard.py`: `_read_payload` bytes read + charset chain (utf-8 → locale → replace) + non-dict guard
- [x] 5.2 `KUNGLAO_WG_DEBUG=1` trace channel (`_dbg` at main() decision points + adjudicate leg counts)
- [x] 5.3 Target file 10/10 green; legacy `test_write_guard_532.py` + `test_write_guard_supersedes_528.py` 22/22 (was 7 failed / 15 passed; false-greens converted, no new red). GBK demo: `payload decoded as cp936` → BLOCK rc=2 with both R1 reasons.
- [x] 5.4 R1 / W-2 / supersedes four-carrier semantics untouched (rule legs byte-identical; only payload read + debug lines changed)

## 6. Gates + PR

- [ ] 6.1 `uv run python devkit/quality_gates.py` (all 7; Gate 2 per known-red ledger: no failures outside the ledger)
- [ ] 6.2 Commit ③ GREEN; push; `gh pr create --base dev` with root cause + RED/GREEN evidence + acceptance table + `Closes #686`
- [ ] 6.3 Report: PR number, RED commit sha, one-line root cause, 7-gate summary, 9/9 + 23/23 evidence

## 7. Post-merge (out of this PR, per batch plan)

- [ ] 7.1 Remove `tracked: #686` quarantine entries from `tests/v013_acceptance/conftest.py`; full-suite re-run for no new red
