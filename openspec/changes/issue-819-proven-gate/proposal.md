# Proposal: issue-819-proven-gate

## Why

豆包现场实锤（issue #819 body v2）：register 的 status→PROVEN 迁移没有证据前置门——谁把 claim-register.yaml 改成 PROVEN 谁就是结算，verify 结果不参与迁移。04:04 C-002 verify REJECTED → register 照刷 PROVEN。完成状态与证据层脱钩 = "假胜利"病理的数据层通道（HIGH）。

## What Changes

1. 新模块 `scripts/register_proven_gate.py`（fail-closed 证据谓词，可复用）：
   - 输入 (ws, new_text, old_text)，diff 出 →PROVEN 迁移
   - 证据要求（issue：最近 verify=PASS + L2 已运行 或 显式豁免）：
     a. 该 claim 最近的 verify-note 结果 = `passes`
     b. 该 claim 有红队运行记录且最近结果 ≠ REFUTED
     c. 或 waiver：`runs/proven-waiver-<claim>.md` 含非空 `justify:` 行
   - waiver 使用即落 ledger 事件 `proven_waiver_used`（可观测）
2. hooks/write_guard.py register 载体增 proven-gate leg：post-image 与在盘 register diff 出 →PROVEN 迁移，证据不足即 BLOCK rc=2、寄存器不变、reason 进 stderr+ledger（write_blocked）
3. rollup.py sweep 事件措辞改记账语义（issue 修复项 2）：detail 改 "rollup of already-terminal claim (accounting only)" + 携带证据引用（依据的 verify/redteam 文件名）

## Impact

- **Affected code**: scripts/register_proven_gate.py（新）、hooks/write_guard.py（register leg + waiver 事件）、scripts/rollup.py（sweep 措辞+证据引用）
- **不变**：TERMINAL 枚举、(claim_id, status) 幂等语义、现有 exit code 约定、TERMINAL 外状态迁移不受影响（只门 PROVEN）
- **明确不做**：#825 身份绑定（W2）；issue 修复项 3"PROVEN 后 verify 防回写"（unglao-verify 面见 PR 描述，本 PR 范围外）；#204 P2 校准 join
