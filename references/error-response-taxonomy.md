# Error Response Taxonomy — issue #448

> 单一引用源:动作错误的强制响应分类(stop / retry-once / ask / escalate)。
> 与三态宪法(references/agent-three-state-charter.md)联动;优先级声明见下。
> 机械分类表在 `scripts/error_response.py`;LLM 兜底漏召回(教义同 #447:
> 机械优先,LLM 补枚举盲区,判断落回结构化声明)。

## Why

2026-08-17 实测四连绕行(issue #448 证据 2):每个"绕一下"单独看合理,
链起来就是授权越界 — T1 init exit 4(HARD REFUSE)后转头扫子网;T2 VPMC
失败直接改 .vmx(还改错 VM);T3 锁冲突直接删锁;T4 通道挂死换脚本绕过。
错误的响应等级由临场决定,且无一处记录"为什么选了这个响应"。

## 分类表 (THE SINGLE SOURCE)

| 错误类 | 机械信号(可枚举) | 强制响应 | 对应宪法状态 |
|---|---|---|---|
| **HUMAN-EVENT-REFUSE** | kunglao-init exit 3/4(#304 人工事件);review-gate BLOCKED | **STOP** — 停止该路径,转告人工,不得代理修复 | must-stop |
| **CONFIG-CHANGE-REQUIRED** | vmrun "操作被取消/取消/canceled"(VPMC 加电失败);任何需要改 .vmx / VM 配置才能继续的错误 | **ASK** — 身份歧义 + 配置变更双重 must-ask | must-ask |
| **IDENTITY-AMBIGUITY** | 多 VM/多 toolchain 匹配;"which VM" 类措辞 | **ASK** | must-ask |
| **TRANSIENT-LOCK** | "文件正在使用中/file is in use/locked/锁冲突" | **RETRY-ONCE** — 仅限同方法重试一次;再失败 → ASK | allowed→ask |
| **TRANSIENT-TIMEOUT** | 网络超时/连接重置 | **RETRY-ONCE** — 同上 | allowed→ask |
| **CHANNEL-FAILURE** | guest 通道挂死(runProgramInGuest 挂起/无响应);MCP bridge 断连 | **ESCALATE** — 上报通道级故障,禁止换方法绕过 | must-ask |
| **PENDING-DECISIONS** | kunglao-init exit 8(RC_PENDING_DECISIONS) | **ASK** — pending decisions 本身就是 must-ask 面 | must-ask |
| **TOOL-INSTALL-HARD-FAIL** | toolchain_install degrade_report HARD 项 | **STOP** — 该项保持 FAIL,人工装(#408 语义) | must-stop |
| **未分类(漏召回)** | 机械表没命中 | **ASK**(默认最安全 — 禁止静默继续/静默绕过) | must-ask |

## 响应定义

| 响应 | 允许的动作 | 禁止的动作 |
|---|---|---|
| **STOP** | 停止当前路径 + 转告人工 + 记录错误原文 | 任何代理修复;任何"绕一下";继续执行 |
| **RETRY-ONCE** | 同方法重试 1 次(需记录重试理由) | 换方法;改配置;第二次重试 |
| **ASK** | 按 must-ask 通道问用户(charter Type D) | 自行选择;自行改配置;静默降级 |
| **ESCALATE** | 上报故障层级 + 停止依赖该通道的工作 | 换工具/换脚本绕过;假装通道正常 |

**绕行反模式**:错误响应只能是上表四类之一,永远不是"换个方法达到同一
目标"(那是 T4 的事故)。换方法 = 新动作 = 需要新的授权判断,不是错误
响应。

## 优先级声明(规则冲突裁决)

**人工事件门禁 > 分析循环不反问规则。**

当 HARD 人工事件门禁触发(kunglao-init exit 4、review-gate BLOCKED)时,
宪法硬禁止 #1("默认 allowed,自己决定继续")**不适用** — 该错误类强制
STOP+转告,继续执行即违规。两份文本(#304 修正案 vs 硬禁止 #1)在此
声明优先级:前者胜。

## 执行器

| 面 | 执行器 |
|---|---|
| 机械分类 | `scripts/error_response.py`(CLI + library;error code / stderr 签名匹配,文法可枚举) |
| 工具安装路径 | `toolchain_install.py` degrade_report(HARD 项 = STOP,已接) |
| VM 操作路径 | `error_response.py` vmrun 签名表;runtime 全接线 = follow-up |
| init 路径 | exit code 本身即分类(init 3/4 → STOP,init 8 → ASK) |
| LLM 兜底 | orchestrator 读本文档(docs 即 prompt);判断落回结构化声明 |

## 验收对照

- [x] 分类表文档 + ≥3 关键路径 gate 化(工具安装 / VM 操作签名 / init exit code)
- [x] 规则文本含优先级声明段落(本文 + rules/kunglao-convergence-loop.md)
- [x] 冲突场景回归测试(tests/test_error_response.py: init exit 4 → STOP 且 allowed_actions 为空)
