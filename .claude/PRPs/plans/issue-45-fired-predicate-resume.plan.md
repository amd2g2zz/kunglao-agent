# Plan: fired-predicate resume prompt（#45，kick 后 fresh session 续接）

## Summary
L3 **RECOVER** 的 prompt 质量：kick 后的 resume prompt 从 **fired predicates**（ledger 末行 + open claims + facts 计数 + workers + blockers）构造，**绝不**读 dying session 的 narrative（progress.txt / analysis_state 自述）。

## 问题 → 方案
- **问题**：#39 初版 `build_resume_prompt` 是简化版（`heartbeat_loop_prompt` 输出拼接，泛泛）。dying session 的 `progress.txt` 叙述（"我正在分析 C-007"）是 LLM 自述，不可信——F4："an LLM saying done is not an event"。
- **方案**：升级 `build_resume_prompt` 为 fired-predicate 版——只读机械 logged state（ledger / claim-register / facts/_INDEX / worker-status）。

## Metadata
- **Complexity**: Small（重写 1 函数 + 测试）
- **Source issue**: #45（parent #39, blocked-by #39 改 #39 初版 `build_resume_prompt`）
- **Research**: F4（commitment drift 0.00→1.00, "LLM saying done ≠ event"）→ `research/long-horizon-agent-failure.md`

## Mandatory Reading
| Priority | File | Why |
|---|---|---|
| P0 | `issue-39-external-kicker.plan.md` Task 2 的 `build_resume_prompt`（fired-predicate 版完整代码） | 逐字移植 |
| P0 | `research/long-horizon-agent-failure.md` F4 | fired-predicate 根因 |
| P1 | `scripts/heartbeat_loop_prompt.py:31-46` | `PROMPT_SOURCE` pattern（resume 末尾拼接 heartbeat loop prompt） |
| P1 | `scripts/convergence_check.py` `_append_ledger` / `_open_claims` | ledger 字段 + open claim 判定 |

## Patterns to Mirror
见总设计 plan 的 `PROMPT_SOURCE` / `LEDGER_READ` / `OPEN_CLAIMS`。

## Files to Change
| File | Action | scope |
|---|---|---|
| `scripts/external_kicker.py::build_resume_prompt` | UPDATE（#39 初版简化版 → fired-predicate 版） | 读 ledger 末行（decision/open_ids/active_workers/blockers/facts_total）+ claim-register OPEN/PARTIALLY-VERIFIED + facts/_INDEX PARTIAL + in-progress worker-status；**绝不读** progress.txt / analysis_state narrative |
| `tests/test_resume_prompt.py` | CREATE | TDD RED 先行 |

## Step-by-Step Tasks

### Task 1: RED — `test_resume_prompt.py`
4 用例（见 issue #45 body TDD）：
- resume 含 ledger 末行 `open_ids`（fired predicate）
- resume **不含** `progress.txt` narrative（fixture 写"我正在分析 C-007"→ 断言 prompt 不含此句）
- 无 open claims → prompt 含 `CONVERGED, verify report`
- 多 blocker → prompt 列全 blocker id

### Task 2: GREEN — `build_resume_prompt` 升级
代码见总设计 plan Task 2 的 `build_resume_prompt`。逐字移植。关键：
- `parts` 列表只从 ledger / claim-register / worker-status 读
- 不 `open()` progress.txt / analysis_state.txt
- 末尾拼接 `heartbeat_loop_prompt.py` stdout（`PROMPT_SOURCE`）

### Task 3: 验证
`python tests/test_resume_prompt.py` 全绿；fixture dying-session narrative → 断言 prompt 排除。

## Acceptance Criteria（= issue #45 验收）
- [ ] kick 后 fresh session 从机械状态续接
- [ ] prompt 不含 dying session narrative
- [ ] F4 原则落地："LLM saying done ≠ event"
- [ ] RED → GREEN → PR → dev

## Risks
| Risk | Mitigation |
|---|---|
| open claims 过多撑爆 prompt | 按 priority 截断 + "（N more, see claim-register）" |
| 漏读 blockers → fresh session 不知道为何卡 | parts 显式列 `blockers` 字段 |
