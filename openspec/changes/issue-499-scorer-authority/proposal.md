# Scorer Authority: priority_ratio 唯一权威声明 + live 路径切换 (#499)

## Why

Issue #499(架构审计 G/F 类):仓库存在**两套 next-claim 评分器**,权威未声明:

- `scripts/priority.py` — 加权和(value×0.4+leverage×0.3+cheapness×0.2+novelty×0.05+outcome×0.05),
  docstring 自称 "SINGLE SANCTIONED dispatch ranker (v1.9.29, R4)";
- `scripts/priority_ratio.py` — M1 DECIDE VoI-proxy(specs/phase-4/contract.md §1,
  issue #2 血统):`score = [0.45·L + 0.30·D + 0.25·N] / TIER_COST`,
  纯函数零 LLM,13 测试覆盖。

**权威判据是 spec**:specs/phase-4/contract.md §1 landing map 把 DECIDE 的
action ranking 落在 `scripts/priority_ratio.py::priority_ratio`;
scripts/README.md:44 也早已宣告 ratio 为 "sanctioned v1.9.29 dispatch ranker"。
但 **live 循环实际跑的是旧加权和**:

- `hooks/worker_pulse.py:244` 每次派发完成注入 next-up(advisory);
- `hooks/worker_budget.py:59,185` 派发时 deviation 审计(rank #1 硬要求 reasoning);
- SKILL.md ×7 处、rules/kunglao-convergence-loop.md ×3 处、
  scripts/heartbeat_loop_prompt.py ×2 处指示 orchestrator "run priority.py";
- references/decision-rights.md:10 把两个 scorer 并列 ✅(权威未声明的实存样本)。

同词不同义(两套 leverage 语义)、novelty 用尝试计数而非事实饱和、
两处 "sanctioned" 宣告互相矛盾 — G 类契约漂移,#496(top-1 上牙)的前置。

## 穷尽 consumer 核实结论(2026-08-19,worktree 5e185a2 全仓 grep)

**priority_ratio.py 的调用方(代码级,非测试)**:

| 文件 | 性质 | live? |
|---|---|---|
| `scripts/kunglao-decide.py:29,159` | M1 DECIDE 组合 CLI(import+调用,failure-blocked 过滤在此) | 无 hook/SKILL 接线 |
| `scripts/kunglao_eval.py`(多处) | L2 评估 harness(openspec/archive/executable-l2-evaluation) | 非 live |
| `scripts/acceptance_check.py:54-57` | 自检 CLI | 非 live |
| `tests/test_priority_ratio.py` | 13 测试 | — |

→ **修正 issue 的"疑似孤儿"表述**:ratio 不是严格孤儿(3 个代码消费方),
但 **零 live-loop 调用方**(hooks/SKILL/rules 均不触达);live next-up 面由
priority.py 占据。预期成立,按原计划切换。

**priority.py 的调用方**:live hooks ×2(worker_pulse:244 / worker_budget:59+185)、
off-loop CLI ×1(external_kicker.py:618-628)、指示文本(SKILL.md ×7、
rules ×3、heartbeat_loop_prompt ×2、convergence_check.py:6,17,600)、
references ×10、golden 冻结 ×2 面(F-01/F-06 action 文本、claudemd-golden ×3)。

## What Changes

- **权威声明**:`scripts/priority_ratio.py` 是唯一权威 next-claim scorer
  (spec 血统:contract.md §1 + issue #2);`scripts/priority.py` 降级为
  deprecated 兼容模块(docstring 指向权威 + `DEPRECATED`/`AUTHORITY` 常量,
  API 逐字节不变,删除走 #446 退役流程)。
- **live 路径切换(使声明机械为真)**:
  - worker_pulse next-up:subprocess 目标 priority.py → priority_ratio.py
    (--json shape 适配:claim_id/action/score;caller 侧过滤 failure-blocked
    —— contract 明文 "failure-blocked filtering is the caller's job");
  - worker_budget check_priority:deviation 审计改用 priority_ratio 排名
    (否则同一轮两个 hook 给出矛盾的 #1,声明不完整);
  - 指示文本翻面:SKILL.md ×7、rules ×3、heartbeat_loop_prompt ×2、
    references(guardrails/search-policy/failure-modes×2/_INDEX/decision-rights/
    tool-inventory)+ scripts/README。
- **防回归测试**:tests/test_scorer_authority.py — 判别性 fixture
  (加权 #1 ≠ VoI #1)e2e 断言 pulse 推 VoI-top;check_priority 同 fixture
  审计方向断言;deprecated 面 + 静态接线断言。

## Impact

- **代码**:hooks/worker_pulse.py、hooks/worker_budget.py、scripts/priority.py(降级不改 API)、scripts/heartbeat_loop_prompt.py、scripts/convergence_check.py(仅 docstring 6,17)。
- **文本**:SKILL.md、rules/kunglao-convergence-loop.md、references/×7、scripts/README.md。
- **测试**:新增 tests/test_scorer_authority.py;更新 tests/test_heartbeat_off.py:133(与新文本同步);tests/test_convergence_rules_file.py ALLOWED_VOCABULARY +1。
- **不做**:golden 冻结面不改(F-01/F-06 action 文本、claudemd-golden ×3、convergence_check.py:600 — contract 冻结 decide() 输出,golden 刷新属 #446 退役pass);external_kicker 保留在 shim(off-loop 手动工具,#446 处置);priority_ratio.py 本体零改动(权威已 13 测试覆盖);#495 三产物对接仅评估不改码(见 design R6)。
