# tools/ 工具家说明

> 本目录是 kunglao-agent 的**工具家(toolshelf)**: 脚本工具 + 索引契约。
> 工具按 6 个能力域分类, 每类一份渐进式披露索引; 机器契约在 `_INDEX.yaml`,
> 由 `validate_index.py` 校验(exit 0=通过 / 1=失败, 可被 gate 调用)。

## 阅读顺序

worker 被派发任务后按以下顺序读, **不需要打开 .py 源码**:

1. `tools/_INDEX.md`(类目表)→ 选类目;
2. `tools/_index-<category>.md`(每工具契约条目: 用途/用法/输入/输出/exit code/when_not)→ 复制用法命令构造调用;
3. `tools/_INDEX.yaml`(机器契约, gate/脚本消费)。

本 README 是**家说明**(给登记/维护者), 不承载工具契约。

## 结构规则(#340)

1. **类目 id == 目录名**: `_INDEX.yaml` 的每个 `category` 值必须同名于
   `tools/<category>/` 目录(crypto/static/ghidra/auxiliary/pipelines);
   唯一例外 `dynamic` — 能力由 MCP + VM 通道提供, 无本地目录
   (#339 已删真空壳 `frida/`、`t2/`, 禁止重建)。
   对齐方向是 id 改随目录(而非目录改随 id): `aux` 是 Windows 保留设备名,
   目录不可能叫 `aux`, 故 #340 将类目 id `aux`→`auxiliary`、
   `pipeline`→`pipelines`(capability 前缀 `aux:*`/`pipeline:*` 是能力
   命名空间, 不随类目 id 改)。
2. **工具脚本一律入类目目录**: 每个注册工具的 .py 住在 `tools/<category>/`。
   tools/ 根层只允许索引/文档文件(`_INDEX.md`/`_INDEX.yaml`/
   `_index-<category>.md`/`README.md`)与下述元工具例外。
3. **根层元工具例外(文档化)**: `tool-search.py` 与 `validate_index.py`
   留在 tools/ 根层 — 它们是 toolshelf 的元工具, 操作对象是
   `tools/_INDEX.yaml` 自身(查询/校验)而非样本, 不属于任何分析类目;
   两者的缺省索引路径按 `Path(__file__).parent / "_INDEX.yaml"` 解析,
   与 `_INDEX.yaml` 同层是这一契约的一部分。`tool-search.py` 刻意不注册
   索引(查询者不进被查者名册)。
4. **共享库单点 `tools/_lib/`**: 跨类目共享的纯库模块(无 CLI 入口,
   不注册索引)归 `tools/_lib/`(当前: `lib_disasm.py`, PE/capstone
   VA→offset 核心)。使用者自行把 `tools/_lib` 加上 `sys.path`。
5. **一类目一个共享模块**: 每个类目目录至多一个共享助手模块
   (static: `common.py` — #340 已把原 `common.py`(CLI plumbing)与
   `_common.py`(byte-scan helpers)合并, 全部公共面保留; crypto:
   `algorithms.py`; ghidra: `job_store.py`)。不得新增第二个共享模块,
   扩展现有模块即可。
6. **`__pycache__` 不入库**: `.gitignore` 的 `__pycache__/` + `*.pyc`
   对 tools/ 任意深度生效(`git check-ignore` 机械验证,
   `tests/test_tools_structure_340.py` 断言)。

结构契约的机械断言见 `tests/test_tools_structure_340.py`。

## 分类结构

```
tools/
├── _INDEX.yaml            # 机器契约: 工具注册表(schema tools-index/1)
├── _INDEX.md              # 顶层 6 类域索引(渐进式披露入口, 风格对齐 references/_INDEX.md)
├── _index-<category>.md   # 每类契约条目(每工具 H3 条目, 6 必填段); 文件名 == 类目 id
├── README.md              # 本文档: 结构规则 + 分类结构 + 契约字段 + MD 格式规范 + 登记流程
├── tool-search.py         # 元工具(根层例外): _INDEX.yaml 确定性查询, 不注册索引
├── validate_index.py      # 元工具(根层例外): _INDEX.yaml 机器契约校验器
├── _lib/                  # 跨类目共享库单点: lib_disasm.py(PE/capstone VA→offset)
├── crypto/                # crypto 类目: crypto-tool.py + algorithms.py(共享模块)
├── static/                # static 类目: 静态 CLI + 共享 common.py(#340 双模块合并) + yara-rules/
├── ghidra/                # ghidra 类目: run_ghidra_postscript.py + postScript Java 源 + job_store.py
├── auxiliary/             # auxiliary 类目: sanitize/audit/capture/measure 工具
└── pipelines/             # pipelines 类目: build_evidence_index.py + recipes/*.yaml plan 模板
```

6 个能力域:

| Category | 含义 | 示例工具 |
|---|---|---|
| `crypto` | 加解密/编解码/哈希 | `crypto-tool` |
| `static` | 静态识别/特征提取 | `die-probe`, `pe-analyze`, `yara-scan` |
| `ghidra` | Ghidra 反汇编/函数分析 | `ghidra-recon` 等 5 件 |
| `dynamic` | VM 动态调试/运行时分析(**VM-only**, 无本地目录) | `x64dbg-remote`, `frida-remote`(MCP 提供) |
| `pipelines` | 证据索引/报告管线 | `build-evidence-index` |
| `auxiliary` | 辅助/杂项 | `sanitize-text`, `measure-cold-start` |

### 外部能力(不在本 toolshelf, 不注册 `_INDEX.yaml`)

- **Frida 动态插桩**: MCP `mcp__frida__*` + VM 通道 `192.168.20.128:1337`; hook 模板在 `templates/frida/`。
- **x64dbg 远程调试**: MCP `mcp__x64dbg__*`(仅 `connect_remote`, 宿主禁止其余调用)。
- **T2 仿真/模拟执行**(Qiling/unicorn): 外部 skill `/malware-framework`。
- **plan 编排模板**: `tools/pipelines/recipes/*.yaml`(纯数据 recipe, 实例化接线为后续工作)。

### 空壳目录处置记录(#339)

- `tools/frida/`(仅 README, 无任何 .py/.tmpl/.js/.yaml 人造物)→ 已删除; Frida 能力由 MCP + VM 通道提供, 模板在 `templates/frida/`。
- `tools/t2/`(仅 README)→ 已删除; T2 模拟能力由外部 skill `/malware-framework` 提供。
- `tools/pipelines/`(README + 5 件 `recipes/*.yaml`)→ 保留; 是真实人造物(plan-recipe/1 模板)。

## 契约字段含义(`_INDEX.yaml` 每个条目)

| 字段 | 必填 | 类型 / 枚举 | 含义 |
|---|---|---|---|
| `name` | 是 | string, 唯一 | 工具名, lowercase kebab-case |
| `category` | 是 | `crypto\|static\|ghidra\|dynamic\|auxiliary\|pipelines` | 能力域(id == 目录名, 决定归入哪个 `_index-<cat>.md`) |
| `capability` | 是 | `"<domain>:<operation>"` | 能力标签, 如 `crypto:decode` |
| `tier` | 是 | `T1\|T2\|T3` | 执行层: T1=静态工具 / T2=模拟执行 / T3=VM 动态 |
| `cost_tier` | 是 | `probe\|cheap\|deep` | 成本档: probe=秒级快查 / cheap=分钟级 / deep=重工具或 VM 会话 |
| `input_output` | 是 | 非空 str 或 `{input, output}` | 输入→输出契约(机器可解析) |
| `when_not` | 否 | 非空 string | 何时**不用**此工具(反选提示) |

校验规则见 `validate_index.py`(name 唯一 / category 6 类 / tier 枚举 / cost_tier 枚举 / input_output 非空; 可选字段出现则须非空)。

## MD 格式规范(#339, 适用 tools/ 内全部 markdown)

1. **标题层级**: 每个文件恰好 1 个 `#`(H1, 文件标题); 章节用 `##`(H2); 每工具契约条目用 `###`(H3, 标题即工具名); 禁止 H4 及更深。
2. **契约条目模板**(每个 `_index-<category>.md` 条目, 段顺序固定):

   ```
   ### <tool-name>

   - **用途**: 一句话
   - **用法**:
     (围栏代码块: 可直接复制的命令, 必填参数齐全; 首行 python tools/... 或 mcp__...)
   - **输入**: 输入形状与必填参数
   - **输出**: 输出形状(JSON/清单/文件)
   - **exit code**: 三态语义(0 成功 / 1 负发现 / 2 错误; 个别工具自带定义, 见条目)
   - **when_not**: 与 _INDEX.yaml 的 when_not 一致
   ```

3. **表格**: 仅用于概览清单(类目表/工具清单); 用法命令不进表格(放围栏代码块); 单元格内禁止换行与未转义 `|`。
4. **列表**: 无序用 `-`, 有序用 `1.`; 嵌套 ≤2 层。
5. **中英策略**: 术语(工具名/参数名/文件路径/字段名/exit code)保持英文原文; 解释说明用中文; 不在术语后加括号译名(术语即权威名)。
6. **单一权威**: 工具契约只在 `_index-<category>.md` 出现一次, 其余文档只引用不复制; `_INDEX.yaml` 是机器契约唯一权威, md 不得与其冲突。

格式与契约的机械断言见 `tests/test_index_docs_contract.py`。

## 如何登记新工具

1. 在 `tools/_INDEX.yaml` 的 `tools:` 列表追加一条(参考文件头的注释示例), 填全 `name` / `category` / `capability` / `tier` / `cost_tier` / `input_output`, 按需加 `when_not`。
2. 在对应域的 `tools/_index-<category>.md` 追加契约条目(按上文"契约条目模板"的 6 段格式, `### <name>` 标题)并同步"工具清单"表一行。
3. 如属新能力域, 先更新 `tools/_INDEX.md` 的 Category table + Per-category index files, 再新建 `tools/_index-<cat>.md` 骨架。
4. 校验:
   ```bash
   python tools/validate_index.py   # exit 0=通过 / 1=失败(打印错误清单)
   python -m pytest tests/test_validate_index.py tests/test_index_docs_contract.py -q
   ```

## 纪律

- `_INDEX.yaml` 是**唯一权威**机器注册表; `_index-*.md` 是给人看的披露索引, 内容不得与 yaml 冲突。
- `dynamic` 域工具一律 VM-only(见 CLAUDE.md 硬约束), 登记时 `tier` 必为 `T3`。
- 契约字段增删改必须同步 `validate_index.py` + `tests/test_validate_index.py`(TDD: 先 RED); 条目格式增删改同步 `tests/test_index_docs_contract.py`。
