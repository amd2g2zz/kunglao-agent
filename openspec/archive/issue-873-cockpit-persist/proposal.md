# issue-873-cockpit-persist — proposal

## Why

座舱/性能指标显示与持久化脱节（#873 审计三缺口）。审计过程中追加发现**第零缺口**：
`cost_events.jsonl` 的 PostToolUse 写入方在仓库内不存在（cost_gate.py 只读不写，
docstring 声明的 "written by PostToolUse hook" 是纸面）——没有输入端，
cost/burn 的读取与持久化都是对空文件的设计。故本卡范围 = 输入端 writer + 三缺口持久化。

## What

1. **缺口0 输入端**：`hooks/cost_input_capture.py`（PostToolUse，Edit|Write|MultiEdit|Agent
   matcher）——tool_result 含 "COST WARNING: session total ~$<float>" 时追加
   {"ts","amount","source"} 到 <ws>/cost_events.jsonl（schema 与 cost_gate 解析器一致）；
   无匹配不写；IO 异常 fail-open（永不阻塞工具流）
2. **缺口1 座舱采样**：heartbeat_tick 报告写盘后调 cockpit_summary →
   ledger 落 action=cockpit_sample 行（v/d_slope/eta_checkpoints/answered/blocked/
   unattempted/cost_spent/cost_remaining/burn 字段齐）；runs/mission_ledger.yaml
   缺失的旧 workspace 跳过（不发零值噪声）；异常 fail-open
3. **缺口2 rho_pair cost**：rho_pair 行增 cost 字段（=cost_events 最新 amount，
   会话级累计口径，proposal 声明）
4. **缺口3 burn 序列**：cockpit_sample 行携带 cost_spent（cost_events 求和）+
   cost_remaining（hard_cap − spent，默认 cap 50.0 与 cost_gate 一致）——
   趋势线由行序列离线重放
5. tuition_curve 学费曲线改读真实 cost（duration 代理路径删除）
6. EMIT_ACTIONS 注册 cockpit_sample（字母序）

## 约束

- 全走 #818 schema（arm/epoch/version 沿用）
- 无新渲染层（消费归未来座舱卡）
- 无 mission_ledger 的 workspace：不 cockpit_sample、不 rho cost（None）——零噪声
- 既有测试不回退

## Out of scope

- statusline 渲染本体（蓝图 §13，未来卡）
- 真实 API 计费接入（Claude Code 未暴露 per-call 计费遥测；input 端为
  PostToolUse 文本解析口径，已在 hooks/cost_input_capture.py docstring 声明边界）
