# Dispatch Protocol — issue #452 (派发协议结构化)

## 为什么

`hooks/dispatch_gate.py` 当前用正则 `[T<N> tools=...] claim <C-NN>`
解析 prompt:
- 解析失败时 `return 0` (silent)— **识别失败无任何可观察信号**
- 无版本字段,正则微变即破坏(MITRE L2-9)
- orchestrator prompt 格式变化时 gate 静默失效

设计目标:
- **可观察**:识别失败必须 emit 可观察信号(stderr / hookSpecificOutput)
- **可演进**:版本字段,新版本加字段不破坏老调用方
- **可机器解析**:JSON > 正则;gate 应优先尝试 JSON

## 协议 v1 (新)

JSON 前缀嵌入 Agent tool prompt:
```json
{"kunglao_dispatch": {"version": 1, "claim": "C-409", "tier": 1,
  "tools": ["pe_analyze", "strings-classify"], "agent": "ghidra-light"}}
```
字段:
- `version`: 协议版本号(整数)
- `claim`: 必填,格式 `C-\d+`
- `tier`: 必填,1 / 2 / 3
- `tools`: 可选,字符串列表
- `agent`: 可选,worker 名(如 `ghidra-light` / `floss-filter`)
- `task`: 可选,自由文本任务描述
- **`reversible`: 可选,布尔(#447 机械优先,LLM 兜漏召回)** — agent 显式
  声明本次派发是否不可逆。`"reversible": false` 是**语言无关**的 must-stop
  信号:`hooks/dispatch_gate.py` 按结构字段直接 HARD_PAUSE,不做任何自然
  语言推断。缺省 = true(普通派发)。

  谁来决定 reversible 的值:机械层先跑(命令文法命中 `vmrun delete` /
  `git push --force` 即不可逆,无论声明);机械漏召回(措辞没对上任何
  pattern)时,由 orchestrator 的语义判断兜底 — 识别到不可逆即声明
  `reversible: false`,把语义判断落回结构字段。**判断用语义,执行用机械。**

## 协议 v0 (兼容)

`[T<N> tools=a,b] claim C-NN ...` — 现有正则形式,**继续支持**。

## 解析顺序

1. **优先**:JSON 前缀解析(`version: 1` → v1 路径)
2. **回退**:v0 正则(`[T<N> tools=...]` → v0 路径)
3. **失败**:emit warning(打破 silent return 0),返回 0

## 识别失败的信号

gate 解析失败时:
- **stderr**:写 `dispatch_gate: unrecognized dispatch protocol (v0/v1 both failed)`
- **hookSpecificOutput.additionalContext**:注入"dispatch gate 失活"信息,让
  orchestrator 看到 gate 没生效(原 silent 行为隐藏这个事实)

## 兼容性

- v0 prompt 继续工作
- v1 prompt 优先
- 老调用方不需要迁移;新调用方可以选 v1

## 派发 prompt 标记(#496 决策上牙,声明式)

三个 prompt 内标记由 `hooks/dispatch_gate.py` 消费,全部走"判断用语义、
执行用机械"的声明通道(散文枚举不可穷尽,标记可枚举):

- **`agent-reasoning: <理由>`** — 派发目标不是 priority_ratio(#499 唯一
  权威 scorer,经 `worker_budget.check_priority`)的 top-1 时**必须**携带
  (#310 agenttype 门同款纪律):无标记 → REJECT(exit 2);有标记 → 放行
  并留痕(统一日志 `runs/logs/kunglao-*.jsonl`,action=`priority_deviation`)。
- **`capability-disproof: <family> (为何失效)`** — 目标 claim(含其
  `obstacle_for` 父链)的 #495 `validated_capability` 已验证某工具族
  (frida/ghidra/x64dbg/...)而本次派发声明了**不相交**的工具族时**必须**
  携带并命名被证伪的族:轨迹1 例 — frida✓ 在手换 xposed,需出示 frida✗。
  无标记 → REJECT;有标记 → 放行并留痕(action=`capability_switch`)。
- **`[strategy <id>]`** — 可选(机制留接口,不强制):携带时派发放行路径
  追加 `runs/strategy-log.jsonl` 一行;同 strategy 的历史失败(经 #495
  `covers_attempt` 推导,无新增写者)降低该 claim 在 ratio novelty 中的
  得分 — 同一打法反复失败,排名靠后。

## 见

- `hooks/dispatch_gate.py` — 实现
- `hooks/lib_kunglao.py` — `parse_dispatch(text)` 共享解析
- `scripts/priority_ratio.py` — 能力卡纯判据 + strategy novelty 消费(#496)
- `openspec/changes/issue-452-dispatch-protocol/` — 完整 spec/design
- `openspec/changes/issue-496-decision-teeth/` — 决策上牙 spec/design