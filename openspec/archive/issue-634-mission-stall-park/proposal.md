# Proposal: #634 主线停滞指纹 + PARK 合法化语义

## Why

豆包现场：~50 个连续 10 分钟 tick 烧掉 $230+ 零进展——决策状态机只有 4 态，
suspended workspace（既非可派发、非饱和、非阻塞、非收敛）被迫伪装成
DISPATCH/BLOCKED 空转；且主线 V_m 平坦无人发现。系统自己的诊断
（"stable-idle, recommend session end"）没有对应的状态机分支可执行。

## What Changes

1. **State.PARK 第五判定**（issue Part A）：decide() 在 (a) active==0
   (b) 全部 open claims 的 blocker 均 external:true (c) partials==0 时
   判 PARK(reason, wake_condition)，EXIT_PARK=5——替代被强制的
   BLOCKED/DISPATCH 伪装态。loop prompt 映射 PARK → 停跳/廉价 tick。
2. **主线停滞指纹**（蓝图 §7.3，directive）：`stall_mission := ΔV_m=0
   连续 K checkpoint AND open_claims>0`——与动作级零输出指纹互补，专抓
   "动作各异但主线不动"。触发：decision 附 `mission_stall` 标注（提案语义，
   不改终态）+ `mission_stall` 事件落账（EMIT_ACTIONS 字母序注册）。
3. **PARK 合法化**：新 status `PARK`（status_defs.SUSPENDED 集）——
   claim 级 PARK 必带 wake_condition；无 wake_condition 的 PARK 在载体
   一致性检查报违规（规则 f）；PARK 不算 open（退出派发队列，priority
   is_open 排除）；`revive` 通道翻回 OPEN 并落账 `claim_revive`。
4. **空转熔断**（issue Part B）：heartbeat_tick 对 register/_INDEX/
   mission_ledger 哈希连续 N=6（env 可配）tick 不变 → rc=2 +
   idle_circuit_breaker——loop 必停信号，非警告。

## Boundaries

- 不动动作级零输出指纹（zero_output_fingerprint.py）与心跳存活面（#830）。
- PARK 是暂停非终态：不进 TERMINAL；复活走 revive，不走重开语义。
- mission_stall 只标注+落账，不改派发决策（P3 的 Q 表才消费它排序）。

## Tasks

- [ ] scripts/mission_stall.py（stall_mission / park_violations / revive）
- [ ] status_defs SUSPENDED 集 + convergence._open_claims / priority_ratio.is_open 排除
- [ ] convergence_check: State.PARK + EXIT_PARK + mission-stall 标注/落账
- [ ] carrier_consistency 规则 (f)
- [ ] heartbeat_tick 空转熔断 rc=2 + loop prompt 两行映射
- [ ] tests/test_mission_stall_634.py（K 触发/合法 PARK/无 wake 违规/revive/decide PARK/熔断）
