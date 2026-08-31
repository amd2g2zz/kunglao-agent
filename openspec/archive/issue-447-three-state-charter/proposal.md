# Proposal — Agent 行为三态宪法 (issue #447)

## Why

issue #447 证据 1:**三份文本对"什么时候该问用户"答案互不引用、部分互斥**:

| 文本 | 原措辞 | 问题 |
|---|---|---|
| 全局规则 `kunglao-convergence-loop.md` 硬禁止 #1 | "不 mid-iteration 反问 user" | 无条件,不区分事件类型 |
| `scripts/ask_for_direction_gate.py` | Type A/B/C + 3-redirect HARD_PAUSE | 有阶梯但触发维度单一(只有 redirect 计数) |
| init 协商 | 无问询协议 | 身份歧义格缺失 |

实际代价(#447 证据 2):VM 修复链中 agent 自选 D:\vms VM 并改配置,被用户
打断 4 次 — "身份歧义必须问"这一格在三个文本里都不存在。

## What

1. **三态表落地** — `docs/agent_3state_charter.md` 作为唯一权威源:
   - 4 类事件(身份歧义/授权边界/范围变更/不可逆动作)× 3 态(allowed/must-ask/must-stop)
   - 类型字母表 A/B/C/D/S
   - 单调降级原则(allowed 不可强制升,must-ask 不可降,must-stop 不可绕)

2. **三个旧文本改为引用** (#447 验收 #1):
   - 全局规则 `rules/kunglao-convergence-loop.md` 硬禁止 #1 → 引用三态表
   - `scripts/ask_for_direction_gate.py` → 加 Type D/S 检测(执行器)
   - `scripts/kunglao-init.py` → 注释引用(协商接口是 Type D 的 init 执行面)

3. **四维事件各有执行器 + 测试** (#447 验收 #2):

   | 维度 | 执行器 | 测试 |
   |---|---|---|
   | 身份歧义 | `ask_for_direction_gate` Type D | test_identity_ambiguity_* |
   | 授权边界 | `ask_for_direction_gate` Type D | test_authorization_boundary_* |
   | 范围变更 | `ask_for_direction_gate` Type D | test_scope_change_* |
   | 不可逆动作 | `ask_for_direction_gate` Type S **+ `hooks/dispatch_gate.py` must-stop hook** | test_rm_vm / test_git_push_force / test_irreversible_dispatch_hard_pauses |

4. **无冲突措辞** (#447 验收 #3):硬禁止 #1 重写为对表的引用

5. **Pattern 英文-only**(用户指示:中英混合 regex 是坏味道)
   - 移除 Type A/B 的中文 pattern(等用户决定/任务做完了等)
   - Type D/S 新 pattern 全英文

## Priority order (check)

```
Type S (must-stop)  >  Type D (must-ask)  >  Type C (convergence)  >  Type A/B (reject)
```

- S 最优先:不可逆动作无论收敛状态都拦
- D 次之:歧义事件即使有收敛信号也必须问
- C 只豁免 A/B(收敛签核是唯一允许的问)

## Files

- `docs/agent_3state_charter.md` (NEW)
- `rules/kunglao-convergence-loop.md` (硬禁止 #1 重写)
- `scripts/ask_for_direction_gate.py` (Type D/S + 优先级)
- `scripts/kunglao-init.py` (注释引用)
- `hooks/dispatch_gate.py` (must-stop hook)
- `tests/test_ask_for_direction_charter.py` (NEW, 18 tests)
- `tests/test_dispatch_protocol.py` (加 TestDispatchMustStop, 3 tests)
- `openspec/changes/issue-447-three-state-charter/{proposal,design,spec,tasks}.md` (NEW)
