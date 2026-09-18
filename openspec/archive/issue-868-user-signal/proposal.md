# Proposal: issue-868-user-signal — 用户反馈生命周期（双门验证）

## Why

全部 lifecycle hook 只监听 agent 行为；用户输入在价值/认知环中不可见。
中途反馈只能一次性手改（#711 证据 2），re-pin 无机制（#606），事实性
反馈无验证通道。设计定稿（2026-09-01，文献落地）见 issue #868 body：
CEGAR + 强 Goodhart + PVG + weak-to-strong。

## What Changes

- `scripts/user_signal.py`（新）：捕获分类核心——本体三类路由
  （volition/factual/meta）、前缀+关键词两级 classified_by、
  意愿类生效（task_spec value_frame + mission_ledger.repin delta）、
  事实类立案（runs/user-signals/）、座舱数据面
- `scripts/dual_gate.py`（新）：双门验证引擎——redteam 反例
  disclosed/held-out 切分、verifier 正向核验、#825 身份绑定异票、
  失败签名分流（诚实=CEGAR 全披露 / Goodhart=最小信号+replan）、
  held-out 复检、N=3 升级、搜索边界声明强制
- `hooks/user_signal_capture.py`（新）：UserPromptSubmit 面，
  fail-open 双笼
- `scripts/mission_ledger.py`：+`repin()` delta API（保 answered 态）
- event_taxonomy：+user_signal / user_signal_processed /
  signal_gate_escalate / signal_gate_pass / signal_gate_reject（字母序）
- hook_activation ALL_HOOKS / wire_up_settings：注册 user_signal_capture
- catalog / deploy-manifest 同步

## Capability Intent

用户信号获得最高提议优先级、零真值特权：意愿域主权直通可撤销；
事实域双门验证（反例切分 + 正向核验），错信号死在二级赌注并成为
校准数据。分错类不丢信号（一级兜底=全量进上下文）。

## Out of Scope

LLM 分类面（P2 接口）；PARK 的自动 wake 判定（#634 语义）；宪法
常量修改（不可达）。
