# Design — 派发协议结构化 (issue #452)

## Architecture

```
                orchestrator prompt
                       │
                       ▼
        hooks/lib_kunglao.py:parse_dispatch (single source)
                       │
            ┌──────────┴──────────┐
            ▼                     ▼
   v1 (JSON) match        v0 (regex) match
   {"kunglao_dispatch":    [T<N> tools=a,b]
    {"version":1,...}       claim C-NN
            │                     │
            └──────────┬──────────┘
                       ▼
              (tier, tools, claim_id)
                       │
                       ▼
        hooks/dispatch_gate.py
                       │
       ┌───────────────┼───────────────┐
       ▼               ▼               ▼
   matched:        unmatched:    not-claim:
   normal flow    _warn_        silent
                  (stderr +
                   hookSpecificOutput)
```

## 协议细节

### v1 JSON Schema (informal)

```json
{
  "kunglao_dispatch": {
    "version": 1,           // required, int, ==1
    "claim": "C-409",       // required, matches C-\d+
    "tier": 1,               // required, 1|2|3
    "tools": ["..."],        // optional, string[]
    "agent": "ghidra-light", // optional, str
    "task": "..."            // optional, free text
  }
}
```

字段验证:
- `version` 必须等于 `DISPATCH_PROTOCOL_VERSION` (=1)
- `claim` 必须匹配 `re.fullmatch(r"C-\d+", claim_id)`
- `tier` 必须 ∈ {1, 2, 3}
- `tools` 非 list → 当作 `[]`

### 解析算法(parse_dispatch_json)

1. 用 `DISPATCH_JSON_START_RE` 找 `{"kunglao_dispatch":` 起点
2. `_balanced_json_at(text, start)` 手写 balanced-brace scanner
   (正确处理 strings + escaped chars,胜过 non-greedy regex)
3. `json.loads()` 整个 JSON
4. 验证 schema,返回元组

为什么不用 non-greedy regex:
- `\{\s*"kunglao_dispatch":\s*\{(.*?)\}\s*\}` 在嵌套 dict/list 时会
  提前闭合(非贪婪匹配到第一个 `}`)
- nested fields 在 v1 payload 是合法的(如 `task: {subtasks: [...]}`)

## 失败信号

`dispatch_gate.py:_warn_unparseable()`:
```python
print("dispatch_gate: unrecognized dispatch protocol (v0/v1 both failed: ...)",
      file=sys.stderr, flush=True)
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "additionalContext": "dispatch_gate: WARN — unrecognized dispatch protocol. ...",
    }
}, ensure_ascii=False), flush=True)
```

两层信号:
- **stderr**:运维 / CI / log 看到
- **hookSpecificOutput**:orchestrator / Claude Code UI 看到

Pre-#452 silent return 0 隐藏了 protocol drift — 这正是 #452 要修的。

## 兼容性

- v0 orchestrator prompt → 继续工作(`[T1 tools=grep] claim C-001`)
- v1 orchestrator prompt → 优先解析
- 老 `DISPATCH_RE` 保留为 backward-compat re-export(`from
  hooks.dispatch_gate import DISPATCH_RE` 仍工作)
- 老 `parse_dispatch(text)` 返回 shape 不变(`(tier, tools, claim_id)`)

## 不变性

- `parse_dispatch` 返回 shape 永远 `(int, list[str], str|None)` — 不破
- v1 `version != 1` → 当作 v0 也匹配不到(兼容老 dispatch)
- warning 不 fail the hook(exit 0) — orchestrator 还能补救

## 测试覆盖

`tests/test_dispatch_protocol.py` (17 tests):
- v1 happy / version-mismatch / invalid-claim / invalid-tier / malformed
- v0 happy / partial-match / no-match
- v1 takes precedence over v0
- warning function unit test (stderr + hookSpecificOutput)
- end-to-end: unparseable prompt → warning emitted
- end-to-end: v1 prompt → no warning
- non-string tools normalized
- `DISPATCH_PROTOCOL_VERSION == 1`