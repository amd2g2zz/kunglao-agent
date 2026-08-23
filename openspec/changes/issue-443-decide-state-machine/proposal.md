# Decide 一等状态机化 — decide() 特判堆 → 显式状态转移表 (#443)

## Why

Issue #443(D1 机制增殖 L2-1/H0,父 issue #498 架构声明 Decide 器官实现件)。
`scripts/convergence_check.py:502-645` 的 `decide()` 是一条 13 分支的 if/elif
特判堆:顺序即语义、注释即规范。证据(issue 正文):

- 证据 1: 同一函数内嵌多类历史事故补丁(#77/#17/M2/#147/#444 W-15 注释),
  每个事故最便宜的修法是"再插一个 elif"——D1 自我强化;
- 证据 2: `grep "class .*State\|STATES\|state_table"` 无匹配,状态由执行
  顺序隐式定义,gate 间隐式交互(如 unverified_pq 只在 opens 为空分支内查)
  只能通读源码推演;
- 证据 3(关联 issue 范围): 同文件活性计算双表示已由 #444 收敛,但决策
  组织方式本身未被触碰(#444 明确 R4 "不动 decide() 分支结构")。

影响面: 修改 decide() 高危——插入/调序可静默改变其它分支可达性,无
invariant 测试兜底。

## What Changes

- **显式状态机**: `decide()` 的判定重组为 `State` 枚举(3 个评估阶段 +
  6 个终态 verdict)+ `Event` 枚举(gate 事件的既有词汇命名)+
  `TRANSITIONS: dict[(State, Event), (State, action)]` 转移表 +
  `STAGE_PROBES: dict[State, list[Event]]`(每阶段事件探测顺序,顺序在
  数据里,不在控制流里)。decide() = 快照 → 查表执行 → 终态 verdict。
- **特判堆消灭**: 13 分支 elif 链删除,归约为表查找;新增守卫/新事件 =
  加一行表数据,不再是插 elif。
- **事件词汇零新增(#446 F 类教训)**: 事件名直接取自已落地词汇——
  #495 失败三产物(`validated_capability` / `identified_obstacle`,经
  `_failure_blocked` → `scan_workspace` 消费)与 #497 梯词汇
  (`LADDER_REQUIRED_BLOCKER` / `LADDER_EXHAUSTED_BLOCKER`,经
  `ask_for_direction_gate.find_ladder_exhaustion` 消费)。不造第二套
  事实词汇。
- **回归锚定(硬验收)**: 重构前 origin/dev@c5cb1ae 的 decide() 与重构后
  对同输入矩阵(~30 case,覆盖每个特判分支 + gate 交织 + 优先级序)
  逐 case 输出相等;锚定快照测试落 `tests/`,永久防漂移。
- **invariant 测试**: 表完整性(每个 (stage, probe) 有转移行)、catch-all
  尾事件、终态映射、decide() 源码零 elif 元守卫、双梯 flavor 同 verdict。

## Impact

- **代码**: `scripts/convergence_check.py`(decide() 重组 + 状态机数据
  结构;helper 函数与输出 dict 字段零变化)。
- **测试**: `tests/test_decide_state_machine.py`(行为测试,RED 先行)+
  `tests/test_decide_regression_anchor.py`(锚定:冻结快照 +
  c5cb1ae 活基线双通道)+ `tests/decide_anchor_c5cb1ae.json`(机器生成
  的冻结快照,生成命令见 design)。
- **调用方零改动**(输出 shape 不变,全仓 grep 确认):
  `convergence_check.main()` / `kunglao-decide.decide()` /
  `kunglao.py cmd_decide` / `worker_pulse`(子进程 --json + exit code)/
  external_kicker(不直接调 decide,读 ledger)。
- **不做**(范围声明,issue 原文): 不改变任何 gate 的语义,不涉及
  notes/verify 层,不改 exit code 语义,不加新决策面(#497 约束)。
  W-15(done_artifact_violations)维持诊断字段地位,#444 R3 的升降级
  决定不在本 issue。

需求源: issue #443 (github.com/amd2g2zz/kunglao-agent/issues/443)
架构约束: issue #498(决策循环一体化);#495/#496/#497 已落地面
