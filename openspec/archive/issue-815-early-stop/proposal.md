## Proposal: #815 早停接线 — infeasible 信号升格为立案（蓝图 L1→L2 提案语义）

### Why

#823-A4 的 `infeasible_signal`（V 平坦 + 发现率 0）只发事件不停手——高投入零产出探索（grep+read 硬啃商业加密 SDK）烧到预算耗尽。蓝图 §7.3：INFEASIBLE 是**需要证据要件的 claim**，不是 V 曲线的属性；直接定性失败=提前宣告失败的镜像病理。

### What

新 `scripts/infeasible_proposal.py`（mirror `dead_letter.mark_dead` 的寄存器变更模式）：

1. **阶梯证据要件**：`runs/infeasible-ladder-<claim>.yaml`——`attempts[]` 必须覆盖恢复阶梯 L1（同 MCP 换模式）/L2（setup 修复）/L3（env-fix worker）三层；`inventory[]`（试过什么/为何失败）非空
2. **立案门槛（fail-closed）**：`file_proposal()` 全部要件齐才放行——信号已运行（runs/infeasible-state.json 存在）+ 阶梯齐 + 清单非空 + wake_condition 非空 + claim 非终态；任一缺失 → REJECT 且**寄存器零变更**、reason 明确（缺哪层/缺什么）
3. **立案落点**：只到 `DEFERRED`（已在 status_defs.TERMINAL → 全消费方自动退出派发），带 `deferred_reason: infeasible` + `wake_condition` + 审计工件 `runs/infeasible-proposal-<claim>.md`（尝试清单表格）；ledger emit `infeasible_filed`（EMIT_ACTIONS 注册）
4. **复活面**：`wake()` — DEFERRED+infeasible 的 claim 带原因回到 OPEN，emit `infeasible_woken`；终态 claim 或非 infeasible DEFERRED → REJECT
5. clawback 接口预留：proposal 工件含 claim 锚（P4 系数环接线点），本批次不实现错杀结算

### Out of scope

issue 全文的 P0 先验编码（re-library 文档）、教训→先验通路（P1）、阈值可调（P2）——属后续卡；本批次只做接线与结构门。

### Impact

- 新脚本 1（+catalog 行）、新 EMIT_ACTIONS 词 2（字母序）、新测试套件 1
- 寄存器 schema：DEFERRED claim 增可选字段 deferred_at/deferred_reason/wake_condition/infeasible_ladder（additive）
- 不改 convergence/priority 消费逻辑（status_defs 单源自动生效）
