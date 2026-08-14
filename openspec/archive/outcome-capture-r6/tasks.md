## 1. Setup

- [x] 1.1 Branch `outcome-capture-r6` off `dev` (f0d44b4) — one issue one PR one branch one worktree (wt35)
- [x] 1.2 Baseline confirmed: scripts/ 144 passed; tests/ 222 passed + 6 pre-existing failures

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 proposal.md (why: r3 75.6% 空转, 验证信号只活文件不进 ledger, OUTCOME 契约零消费者)
- [x] 2.2 design.md (D1-D7: 两本账本隔离 / 容错读 / 幂等 append / verdict 读取 / 纯函数聚合 / SNAPSHOT 兼容)
- [x] 2.3 spec.md (REQ: OUTCOME 行捕获 + 幂等; aggregate_reward 纯函数 None 中性; reward 不 gate)
- [x] 2.4 tasks.md
- [x] 2.5 `openspec validate outcome-capture-r6` PASS

## 3. RED tests (write first, must fail)

- [x] 3.1 test_capture_writes_outcome_row — verify-note passes → 1 行 type=outcome result=passes checker=verify-note
- [x] 3.2 test_aggregate_reward_values — 4 行混合 → (1.0+0.5+0.0+1.0)/4 == 0.625
- [x] 3.3 test_dedup_same_claim_checker — 同 claim 两 verify 文件 + 两次 capture → 幂等不增
- [x] 3.4 test_no_data_neutral — aggregate_reward([]) is None
- [x] 3.5 test_snapshot_rows_ignored — 无 type 的 SNAPSHOT 行 → read_outcome_rows == []
- [x] 3.6 (extra) red-team CONFIRMED/UNVERIFIED-WITH-GAP capture + changed-result 两行

## 4. scripts/outcome_capture.py implementation (GREEN)

- [x] 4.1 read_outcome_rows (镜像 convergence_health._read_ledger + ledger_line_type 过滤)
- [x] 4.2 _seen_key + capture (幂等 append, VERDICT_RE / REDTEAM_RE, claim 抽取 + fallback)
- [x] 4.3 aggregate_reward (纯函数, RESULT_SCORE 映射, None 中性, 防御性 type 过滤)
- [x] 4.4 main CLI (--reward / --json)

## 5. Validation + commit

- [x] 5.1 `pytest scripts/test_outcome_capture.py -v` → 15/15 GREEN
- [x] 5.2 `pytest scripts/ -q` → 159 passed (144 baseline + 15 new), no new failures
- [x] 5.3 `pytest tests/ -q` → 222 passed + 6 pre-existing failures (no regression)
- [x] 5.4 git commit: SDD artifacts (d612161), then feat(outcome-capture) impl+tests (1e13e46)
- [x] 5.5 CLI smoke: capture 2 rows → idempotent re-run 0 new → reward=0.5 (--json ok)
- [ ] 5.6 Report files changed + test counts (no push/PR/merge — orchestrator handles merge)
