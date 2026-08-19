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

## 见

- `hooks/dispatch_gate.py` — 实现
- `hooks/lib_kunglao.py` — `parse_dispatch(text)` 共享解析
- `openspec/changes/issue-452-dispatch-protocol/` — 完整 spec/design