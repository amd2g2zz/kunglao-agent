# proposal: #823-P2 ρ_t 稠密信号（shadow）

## Why

§7.2 蓝图：ρ = 稠密代理，z = 机械真值锚；(ρ,z) 对积累后 Platt 拟合 P(完成)=σ(w·x+b)。
N-arm 骨架已有 fit_platt/rho_from_distribution/parse_verifier_response（rho_checkpoint.py），
缺：可插拔采样后端 + checkpoint (ρ,z) 配对落盘 + 拟合数据通路。

## What Changes

- 新 scripts/rho_verifier.py：
  - DeterministicBackend（默认）：ρ_t = 0.6·V_m 归一化水平 + 0.4·PQ 词法覆盖（PQ 问题词集
    与 facts 语料的交集率，无 LLM 可全绿测试）
  - LlmBackend 接口：env KUNGLAO_RHO_BACKEND=llm 且配置存在才启用；未配置→回落确定性后端
  - sample_and_pair(ws)：checkpoint 采样 ρ_t，与 z（机械终局：全 PQ answered=1，有终局失败
    倾向=0，运行中=None pending）配对，kunglao_log.emit(action="rho_pair") 落账（#818 schema，
    epoch/version 自动）
  - pairs_from_ledger(ws)：读 ledger 的 rho_pair 行回放为 (score, outcome) 对
  - fit_platt：re-export rho_checkpoint.fit_platt（单一来源）
- rho_checkpoint.attach_signals 挂 sample_and_pair（flag 门控 + try/except shadow，永不干扰 decide）
- event_taxonomy.EMIT_ACTIONS 注册 "rho_pair"（保持字母序）
- scripts/README.md catalog 行

## Out of scope

宣称完成先过 ρ 门（P3）；Q 表排序（P3）；系数重拟合（P4）；早停决策变更。
