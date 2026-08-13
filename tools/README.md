# tools/ 工具家说明

> 本目录是 kunglao-agent 的**工具家(toolshelf)**: 脚本工具 + 索引契约。
> 工具按 6 个能力域分类, 每类一份渐进式披露索引; 机器契约在 `_INDEX.yaml`,
> 由 `validate_index.py` 校验(exit 0=通过 / 1=失败, 可被 gate 调用)。

## 分类结构

```
tools/
├── _INDEX.yaml            # 机器契约: 工具注册表(schema tools-index/1)
├── _INDEX.md              # 顶层 6 类域索引(渐进式披露入口, 风格对齐 references/_INDEX.md)
├── _index-<category>.md   # 每类骨架: 一行式契约示例
├── README.md              # 本文档: 分类结构 + 契约字段 + 登记流程
├── validate_index.py      # _INDEX.yaml 机器契约校验器
└── *.py                   # 工具脚本(见 _INDEX.md 的 tools/ scripts 表)
```

6 个能力域:

| Category | 含义 | 示例工具 |
|---|---|---|
| `crypto` | 加解密/编解码/哈希 | `crypto-tool` |
| `static` | 静态识别/特征提取 | `die`, `floss`, `pefile` |
| `ghidra` | Ghidra 反汇编/函数分析 | `ghidra-headless` |
| `dynamic` | VM 动态调试/运行时分析(**VM-only**) | `x64dbg-remote`, `frida-remote` |
| `pipeline` | 证据索引/报告管线 | `build-evidence-index` |
| `aux` | 辅助/杂项 | `file-hash`, `strings` |

## 契约字段含义(`_INDEX.yaml` 每个条目)

| 字段 | 必填 | 类型 / 枚举 | 含义 |
|---|---|---|---|
| `name` | 是 | string, 唯一 | 工具名, lowercase kebab-case |
| `category` | 是 | `crypto\|static\|ghidra\|dynamic\|pipeline\|aux` | 能力域(决定归入哪个 `_index-<cat>.md`) |
| `capability` | 是 | `"<domain>:<operation>"` | 能力标签, 如 `crypto:decode` |
| `tier` | 是 | `T1\|T2\|T3` | 执行层: T1=静态工具 / T2=模拟执行 / T3=VM 动态 |
| `cost_tier` | 是 | `probe\|cheap\|deep` | 成本档: probe=秒级快查 / cheap=分钟级 / deep=重工具或 VM 会话 |
| `input_output` | 是 | 非空 str 或 `{input, output}` | 输入→输出契约(机器可解析) |
| `when_not` | 否 | 非空 string | 何时**不用**此工具(反选提示) |

校验规则见 `validate_index.py`(name 唯一 / category 6 类 / tier 枚举 / cost_tier 枚举 / input_output 非空; 可选字段出现则须非空)。

## 如何登记新工具

1. 在 `tools/_INDEX.yaml` 的 `tools:` 列表追加一条(参考文件头的注释示例), 填全 `name` / `category` / `capability` / `tier` / `cost_tier` / `input_output`, 按需加 `when_not`。
2. 在对应域的 `tools/_index-<category>.md` 追加一行契约示例(格式与现有示例行一致: `` `name` | `category: … · capability: … · tier: … · cost_tier: … · input: … → output: …` | 何时读 / 何时不用 ``)。
3. 如属新能力域, 先更新 `tools/_INDEX.md` 的 Category table + Per-category index files, 再新建 `tools/_index-<cat>.md` 骨架。
4. 校验:
   ```bash
   python tools/validate_index.py   # exit 0=通过 / 1=失败(打印错误清单)
   python -m pytest tests/test_validate_index.py -q
   ```

## 纪律

- `_INDEX.yaml` 是**唯一权威**机器注册表; `_index-*.md` 是给人看的披露索引, 内容不得与 yaml 冲突。
- `dynamic` 域工具一律 VM-only(见 CLAUDE.md 硬约束), 登记时 `tier` 必为 `T3`。
- 契约字段增删改必须同步 `validate_index.py` + `tests/test_validate_index.py`(TDD: 先 RED)。
