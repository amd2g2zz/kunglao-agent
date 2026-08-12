# Plan: state_anchor hook — PostToolUse 状态重锚（#44，治本层）

## Summary
L1 **PREVENT**：worker 完成后 PostToolUse(Agent) 注入紧凑状态签名 + 漂移警告到 `additionalContext`，机械重锚 LLM 状态表示，对抗 context rot。这是 kunglao 缺失的 F5 "forget/refresh" 运行时函数。

## 问题 → 方案
- **问题**：LLM 随 action-observation trajectory 增长丢失精确状态表示（context rot），per-turn 无机械重锚 → 过期状态上演算 → 漂移（#43 检出）+ 假完成（#45 resume）。
- **方案**：`state_anchor` hook 每个 agent tool 完成后注入 ledger 末行摘要 + 漂移警告。FAIL_OPEN（异常返回空串，不阻断 worker）。

## Metadata
- **Complexity**: Small-Medium（1 hook 文件 + `ensure_project_hooks` 加注册行 + 测试）
- **Source issue**: #44（parent #39, blocked-by #43 复用 `signature_rotation`）
- **Research**: F5（deterministic Executive, know/forget/recover）、F1（72.5% process-level → 修 harness 是对的高度）

## Mandatory Reading
| Priority | File | Why |
|---|---|---|
| P0 | `issue-39-external-kicker.plan.md` Task 1 的 `test_state_anchor` 部分 + Task 3 全部（`hooks/state_anchor.py` 完整实现） | 代码 |
| P0 | 同上 Task 2 的 `ensure_project_hooks`（state_anchor 注册行） | 注册逻辑 |
| P0 | `research/long-horizon-agent-failure.md` F1/F5 | 治本根因 |
| P1 | `hooks/worker_pulse.py:173-178` | PostToolUse `additionalContext` 注入范式（`PULSE_INJECT` pattern） |

## Patterns to Mirror
见总设计 plan 的 `PULSE_INJECT` / `ATOMIC_WRITE` / `ACTIVE_STRICT`。

## Files to Change
| File | Action | scope |
|---|---|---|
| `hooks/state_anchor.py` | CREATE | `build_anchor(ws)`（≤500 字符状态摘要 + 漂移警告）+ `main()`（读 stdin JSON payload，仅 `tool_name=="agent"` 触发，FAIL_OPEN，返回 `{"hookSpecificOutput":{"additionalContext":...}}`） |
| `tests/test_state_anchor.py` | CREATE | TDD RED 先行 |
| `scripts/external_kicker.py::ensure_project_hooks` | UPDATE | 加 PostToolUse(Agent) `state_anchor.py` 注册行 |

## Step-by-Step Tasks

### Task 1: RED — `test_state_anchor.py`
4 用例（见 issue #44 body TDD）：agent 完成→注入 decision/open_count；`signature_rotation=4`→警告含 `STATE FLAT`；异常（ledger 缺失）→返回空串不抛；非 agent tool（Bash/Read）→不触发。

### Task 2: GREEN — `hooks/state_anchor.py`
代码见总设计 plan Task 3。逐字移植。关键点：
- `main()` 读 stdin JSON（`tool_name`, `tool_response`），`tool_name != "agent"` 直接 return `{}`
- `build_anchor(ws)` 读 ledger 末行 + 复用 #43 的 `signature_rotation` 判漂移
- 返回 `{"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": anchor_text}}`
- 全程 try/except → 异常返回空串（FAIL_OPEN）

### Task 3: 注册到 `ensure_project_hooks`
总设计 plan `ensure_project_hooks` 的 state_anchor 行：`post = _ensure(post, "Agent", "state_anchor.py")`。

### Task 4: 验证
`python tests/test_state_anchor.py` 全绿；手动 agent tool 完成 → additionalContext 含状态摘要。

## Acceptance Criteria（= issue #44 验收）
- [ ] 每个 worker 完成后注入机械状态签名（不依赖 LLM 自记）
- [ ] 漂移时警告触发 re-read claim-register
- [ ] FAIL_OPEN 不阻断正常流程
- [ ] RED → GREEN → PR → dev

## Risks
| Risk | Mitigation |
|---|---|
| 注入过长撑爆 context | `build_anchor` ≤500 字符，超限截断 + 省略号 |
| FAIL_OPEN 吞真异常 | 异常写 stderr（不阻断 hook 但留诊断） |
