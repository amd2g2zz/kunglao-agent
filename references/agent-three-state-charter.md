# Agent 行为三态宪法 — issue #447

> 单一引用源: agent 在 4 类典型事件中的三态选择 (allowed / must-ask / must-stop)。
> 全局硬禁止 #1、ask_for_direction_gate、init 协商 — 全部声明为这张表的执行器。

## 为什么

issue #447 证据 1 显示**三份文本对"什么时候该问用户"答案互不引用、部分互斥**:

| 文本 | 措辞 |
|---|---|
| 全局规则 `kunglao-convergence-loop.md` 硬禁止 #1 | "不 mid-iteration 反问 user — 自己决定并记 reasoning,继续" (无条件) |
| `ask_for_direction_gate.py` | Type A BAD / Type C OK / HARD_PAUSE @ 3+ redirects (有阶梯) |
| init 协商接口 | 全程无问询协议;非交互 stdin 自动 declined (无) |

→ **同一情境不同会话行为不可预测,用户被迫以"打断"充当规则系统纠错信号**(issue #447 证据 2:VM 修复链 4 次打断)。

## 三态表 (THE SINGLE SOURCE)

| 事件分类 | 事件类型 | 状态 | 处理 |
|---|---|---|---|
| **普通推进** | 默认 case | **allowed** | 自己决定 + 记 reasoning + 继续 |
| **普通推进** | 收敛签到 (C0-C7 all pass) | **allowed** | convergence check per section 8 |
| **身份歧义** | 多 VM / 多 toolchain / 多样本歧义 | **must-ask** | emit Type D 信号 + HARD_PAUSE (rc=2) |
| **身份歧义** | 任务目标歧义 (workflow ≠ evidence) | **must-ask** | emit Type D 信号 + HARD_PAUSE |
| **授权边界** | 有界授权内新硬错误 (#451 风格) | **must-ask** | emit Type D 信号 + HARD_PAUSE |
| **授权边界** | 工具/资源耗尽 (#474 #475 风格) | **must-ask** | emit Type D 信号 |
| **范围变更** | 任务边界扩张(原计划外) | **must-ask** | emit Type D 信号 |
| **不可逆动作** | 删除 VM / 改 vmx / git push --force | **must-stop** | 阻止 + emit Type S + HARD_PAUSE |
| **不可逆动作** | 公开 release / publish | **must-stop** | 阻止 + emit Type S |
| **废话反问** | "should I" / "do you want" / 等用户决定 | **NEGATIVE** (reject) | Type A/B violation (ask_for_direction_gate) |

## 类型字母表

| 类型 | 含义 | 处理 |
|---|---|---|
| Type A | 废话反问问句 | REJECT (rc=1) |
| Type B | 完成-问下一步 | REJECT (rc=1) |
| Type C | 收敛签到 | ALLOWED |
| **Type D** | must-ask 触发信号(身份歧义 / 授权边界 / 范围变更) | HARD_PAUSE (rc=2) |
| **Type S** | must-stop 触发信号(不可逆动作) | HARD_PAUSE (rc=2) |

## 执行器 (谁是这张表的执行者)

| 文本 | 角色 |
|---|---|
| `scripts/ask_for_direction_gate.py` | Type A/B/C 检测 (RC=1 reject)+ Type D/S 触发时 HARD_PAUSE (rc=2) — 看到 orchestrator **打印后** 的文本 |
| `hooks/dispatch_gate.py` | Type S 在 **dispatch prompt 本身** 上拦截 (rc=2 hard pause,worker 运行**前**) — 不可逆动作的承载执行器 |
| `scripts/kunglao-init.py` 协商接口 | init 阶段 Type D 触发 — pending decisions + RC_PENDING_DECISIONS=8 |
| 全局 `kunglao-convergence-loop.md` 硬禁止 #1 | **重写为对这张表的引用**,不直接措辞 |

> 为什么 Type S 需要两个执行器:`ask_for_direction_gate` 只看打印后的
> 输出(orchestrator 可能不打印);`dispatch_gate` 在 PreToolUse 时看
> prompt 本身(worker 运行前拦) — 后者是承载,前者是纵深防御。

## 声明优先于推断(检测教义)

优先级:**机械优先,LLM 只兜机械的漏召回**。

```
第1优先 机械层(便宜、确定、可审计 — 先跑,覆盖内零漏报)
├── 声明字段:派发协议 "reversible": false → HARD_PAUSE(references/dispatch-protocol.md)
├── 命令文法:vmrun delete / git push --force(文法有限,可枚举)→ HARD_PAUSE
├── 结构化状态:claim-register / decision_pending / .hook_state.json
└── regex 绊线:prose pattern(zh+en,非穷尽)
        ↓ 机械漏召回(枚举盲区:措辞没对上任何 pattern)
第2优先 LLM 语义兜底(任何语言,覆盖枚举不到的措辞)
└── orchestrator 读本宪法(docs 即 prompt),语义识别不可逆/歧义
    → 识别结果落成结构化声明("reversible": false),又回到机械可查
```

分工:机械层管**确定性拦截** — 命中即拦,结果可审计、零成本;LLM 管
**召回** — 枚举永远不完,语义理解补盲区。LLM 的判断一旦形成,必须落成
结构化声明:判断用语义,执行用机械,闭环。

用户输入(常为中文)走 intake/decision_pending 结构化 schema 进入系统;
语言在机械层不是变量,LLM 层天然多语。

## 单调降级原则

- **allowed** → 不能强制升级到 must-ask(除非 orchestrator 主动声明触发类型)
- **must-ask** → 不能降级为 allowed(必须问)
- **must-stop** → 不能绕过(用户必须显式 unlock)
- **NEGATIVE** (Type A/B) → 不能借"Type C 收敛"绕过(除非 C0-C7 all pass 真实存在)

## 不变性

- 本表是**唯一**的"何时问用户"权威源
- 任何代码/规则不得**直接**说"问用户" / "不问用户" — 必须引用本表
- 表格变更须经 openspec 流程(版本 + 变更记录)

## 见

- `scripts/ask_for_direction_gate.py` — Type A/B/D 检测
- `openspec/changes/issue-447-three-state-charter/` — 完整 spec