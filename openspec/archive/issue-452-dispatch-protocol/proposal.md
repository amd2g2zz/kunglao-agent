# Proposal — 派发协议结构化 (issue #452)

## Why

`hooks/dispatch_gate.py` 当前用正则 `[T<N> tools=...] claim <C-NN>`
解析 orchestrator 的 dispatch prompt:

- 解析失败时 `return 0` (silent) — **识别失败无任何可观察信号**
- 无版本字段,正则微变即破坏
- orchestrator prompt 格式变化时 gate 静默失效(MITRE L2-9)

设计目标:
- **可观察**:识别失败必须 emit 可观察信号
- **可演进**:版本字段,新版本加字段不破坏老调用方
- **可机器解析**:JSON > 正则

## What

### 协议 v1(新,JSON)
```json
{"kunglao_dispatch": {"version": 1, "claim": "C-409", "tier": 1,
  "tools": ["pe_analyze"], "agent": "ghidra-light", "task": "..."}}
```

### 协议 v0(兼容)
`[T<N> tools=a,b] claim C-NN ...` — 继续支持。

### 解析顺序
1. v1 (JSON, 带 balanced-brace scanner)
2. v0 (regex, fallback)
3. 失败 → emit warning (stderr + hookSpecificOutput)

### 解析失败信号(#452 AC)
- stderr: `dispatch_gate: unrecognized dispatch protocol (v0/v1 both failed)`
- hookSpecificOutput.additionalContext:注入"WARN — Gate INACTIVE"
- 不再 silent return 0

### 实现位置
- `hooks/lib_kunglao.py` — 共享解析器(`parse_dispatch`, `parse_dispatch_json`)
- `hooks/dispatch_gate.py` — 调用共享解析器 + 失败 warning
- 老 `DISPATCH_RE` 保留为 backward-compat re-export

## Why not JSON-only

老 orchestrator / 老 test 都用 v0 形式。强制迁移会引入大量回归。
v0 兼容 + v1 优先 = 渐进迁移。

## Acceptance

- [x] v1 JSON 协议定义 + `parse_dispatch_json()`
- [x] `parse_dispatch()` 优先 v1,fallback v0
- [x] `dispatch_gate.py` 用共享解析器
- [x] 解析失败 emit warning(stderr + hookSpecificOutput)— 不再 silent
- [x] 17 个测试覆盖(v0 / v1 / malformed / precedence / warn)
- [x] docs/dispatch_protocol.md 协议规范

Refs: #452; user directive "派发协议结构化"