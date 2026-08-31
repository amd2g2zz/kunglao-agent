# Trajectory Replay — v0.1.1 双轨迹端到端重演测试 (#498 收尾件)

## Why

Issue #498 是 v0.1.2 的架构声明件("决策循环一体化"), 其验收段要求
**端到端双轨迹重演**: v0.1.1 现场用户反馈的两条失败轨迹(同一任务先提前
宣告失败、后有方案却停下等人)必须在合流后的系统上重演并**被拦截**。
计划 R2 把它固化为里程碑级验收(验收方法 D), 且要求
`tests/test_trajectory_replay.py` 随收尾 PR 进 dev。

全部器官已各自落地并有**单级负例**测试:

- `scripts/failure_analysis_gate.py` (#495 三产物 / BLOCKED / 障碍升格)
  — `tests/test_failure_analysis_transducer.py`
- `scripts/ask_for_direction_gate.py` (#497 TYPE_E 判死 + plan-stall +
  梯前置) — `tests/test_ask_for_direction_v2.py`
- `hooks/dispatch_gate.py` (#496 能力卡) — `tests/test_decision_teeth.py`
- `scripts/kunglao-init.py` + `scripts/hook_activation.py` (#461 心跳自举
  + cron HARD) — `tests/test_heartbeat_bootstrap.py`
- `scripts/kunglao_resume.py` (#466) + `scripts/convergence_check.py`
  (#443 decide 状态机) — 各自测试

但没有任何测试把四条器官**串成轨迹**。单级测试证明每道闸各自关得上;
轨迹重演证明**闸的顺序与接力**在真实事件序列上成立 — v0.1.1 的两条
轨迹恰恰都是"每道闸单看都合规、串起来死掉"的形态(判死宣告是无问句
陈述句, 搁浅是字母合规的"下一步:"声明)。

## What Changes

**只新增一个测试文件, 零器官改动**(合流对象只消费不重写):

`tests/test_trajectory_replay.py` — 四场景, 全部真实 CLI/subprocess 级
(不 mock 器官内部), fixture 全合成:

1. **轨迹1 判死链全链** (`-k trajectory1`): claim + 瞬态失败×2
   (analysis 记录但三产物缺失)+ 判死宣告文本 →
   `ask_for_direction_gate` rc=1 (TYPE_E 拦) 且 `failure_analysis_gate`
   scan rc=1 (BLOCKED); 补三产物 → 障碍升格 claim 出现
   (origin=failure-obstacle + claim_deps 真边) + `convergence_check`
   decide → DISPATCH / `kunglao_resume` next_step 指向派发 —
   **不是死局**。
2. **轨迹2 plan-stall** (`-k trajectory2`): 动作史 → 里程碑总结 +
   "下一步:" → 后续零动作 → ask gate rc=1 (plan-stall); 能力成就
   (frida✓)落为 `validated_capability` 后换 xposed 派发 →
   `dispatch_gate` REJECT capability (stderr 含 frida + disproof 指引)。
3. **心跳自活 e2e** (`-k heartbeat`): 干净 tmp workspace 跑真实
   `kunglao-init.py` (hermetic seam: `--skip-toolchain` / fake
   claude.json / 空 PATH, 镜像 #461 既有 init 测试) →
   `runs/.heartbeat.json` 存在且新鲜、全程零 `hook_activation` 手动
   调用; cron 未注册 → `heartbeat_loop_prompt.py --verify` rc=1 +
   stderr 指引。
4. **看牌变体** (`-k capability_card`): disproof 出示后放行且留痕
   (stderr `CAPABILITY (disproof recorded)` + 统一日志
   `capability_switch` 事件)。

## 风险与对策

- **过度拟合叙事细节**(计划风险行): 负例取行为等价类(判死语法族 /
  停滞语义), 非逐字匹配 — 与 #497 测试同一纪律。
- **init 全链太重**: 按 #461 既有 init 测试的 hermetic seam 模式
  (`--skip-toolchain` + pinned fake `claude.json` + 空 PATH), 不碰
  真实工具链。
- **e2e 组装暴露器官缺陷**: 记录并回报, 拆 follow-up, 不在本件修器官
  (零器官改动硬约束)。
