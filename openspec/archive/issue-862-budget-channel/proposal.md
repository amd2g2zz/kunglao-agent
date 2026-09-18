# issue-862: budget 通道归一（B4 CONFIRMED）

## Why

cid-keyed 门（cap/tier/tools/devreason）在真实派发上静默失效：battery 只从
`description` 解析 dispatch 形状（worker_budget_sinks.py:425-428），而合同规定
形状在 prompt 前缀（dispatch-protocol.md:18 协议 v1 JSON envelope）。测试钉的
也是 description → CI 假绿（B4 CONFIRMED）。同边界双 pass-token 分裂：
dispatch_gate.py:406 要 `agent-reasoning:`，worker_budget_sinks.py:491 要
`reasoning:`。

## What Changes

1. battery 改从合同通道（prompt）解析：v1 JSON envelope 优先（#861 已落地
   lib_kunglao.parse_dispatch 单源，v1-first）
2. 弃用通道 fail-closed：形状出现在 description → REJECT `devchannel`
   （这正是 B4 静默死门的姿态）
3. pass-token 归一：`agent-reasoning:` 为 canonical（与 dispatch_gate 一致），
   devreason 门不再接受裸 `reasoning:`；SKILL.md 同步只教 canonical
4. 测试通道矫正：_budget_payload 默认注入走 prompt；钉错的 4 处改生产通道；
   新增负例（形状仅在 description → 拒）

## Out of scope

无形状派发（非 kunglao Agent 调用）的全局拒绝——需 producer 侧合同，#861 族。

## Impact

- hooks/worker_budget_sinks.py（pre_check 通道 + devreason token）
- skills/kunglao-agent/SKILL.md（reasoning 措辞归一）
- tests/test_worker_budget.py（通道矫正 + 新负例）
- tests/test_budget_channel_862.py（新）
