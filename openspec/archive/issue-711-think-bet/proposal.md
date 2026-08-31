# issue-711-think-bet

## Why

#711 的 THINK 席位（#759 落地）产出的是"pending 占位文书"——没有任何机制让思考产生可结算的后果，于是思考退化为表演（找借口证明努力过）。蓝图 §7.3 的裁定：真思考 = 可证伪下注；文书零奖励，唯一可结算单位 = 假设（predicted_observation）。

## What Changes

1. hypothesis_store：Hypothesis 增 `predicted_observation` 字段；状态机增 `confirmed`（open → confirmed 需 confirming_fact_id；与 refuted 对称）
2. HypothesisStore 增 `create()`（下注立案的唯一入口，predicted_observation 为空即 ValueError——无预测的思考不被采纳）
3. think_seat：读近 K ledger 失败事件（death_verdict_rejected / top1_reject）→ `bets_owed`（失败 claim 无覆盖 bet → 欠注）；artifact 增 `## bets` 强制下注区；**失败触发先例检索**（bets_owed>0 时 suggested_searches 立即出现，不等 stall 计数）——盘古先例案例（不搜=确定性损失）的机制化
4. 结算通道：`settle_bet` confirmed/refuted 双向记账（refuted 追缴语义留 P4，本批次只记账）
5. EMIT_ACTIONS 注册 bet_filed / bet_settled（字母序）

## Impact

- scripts/hypothesis_store.py · scripts/think_seat.py · scripts/event_taxonomy.py
- 不动：#823-P2 ρ_t、#823-P3 Q 表、decide/priority 行为
