# tools/ Domain Index — progressive disclosure entry point

> Orchestrator: read this file once per round, pick a category, dispatch the worker; the worker reads `_index-<category>.md` (per-tool contract entries: 用途/用法/输入/输出/exit code/when_not — 可直接复制调用), then loads `_INDEX.yaml` for the machine contract. Full per-category catalog below the category table.

## Category table

| Category | Index file | Tool shelf (examples) | Purpose |
|---|---|---|---|
| crypto | `_index-crypto.md` | crypto-tool | 加解密/编解码/哈希工具 |
| static | `_index-static.md` | die-probe, pe-analyze, yara-scan | 静态识别/特征提取工具 |
| ghidra | `_index-ghidra.md` | ghidra-recon, ghidra-decompile-functions, ghidra-vtable-struct, ghidra-evidence-annotations, ghidra-scan-pointer | Ghidra 反汇编/函数级分析 |
| dynamic | `_index-dynamic.md` | x64dbg-remote, frida-remote | VM 动态调试/运行时分析(无本地目录, MCP 提供) |
| pipelines | `_index-pipelines.md` | build-evidence-index | 证据索引/报告管线 |
| auxiliary | `_index-auxiliary.md` | sanitize-text, measure-cold-start | 辅助/杂项工具 |

| Scenario | Category |
|---|---|
| 新样本快速识别(语言/编译器/加壳) | static |
| 加密/编码/哈希识别与解码 | crypto |
| 函数级反汇编 / 导入 / xref / 结构恢复 | ghidra |
| 运行时动态验证(单步/断点/hook, VM-only) | dynamic |
| 证据登记 / 索引构建 / 报告生成 | pipelines |
| 哈希 / 文件元数据 / 小杂务 | auxiliary |

## 外部能力(不在本 toolshelf, 不注册 `_INDEX.yaml`)

| 能力 | 提供方 | 入口 |
|---|---|---|
| Frida 动态插桩(hook/attach) | MCP `mcp__frida__*` + VM 通道 `192.168.20.128:1337` | `_index-dynamic.md`; hook 模板在 `templates/frida/` |
| x64dbg 远程调试 | MCP `mcp__x64dbg__*`(仅 `connect_remote`; 宿主禁止其余) | `_index-dynamic.md` |
| T2 仿真/模拟执行(Qiling/unicorn) | 外部 skill `/malware-framework` | 见 [README.md](README.md) 分类结构 |
| plan 编排模板(recipe) | `tools/pipelines/recipes/*.yaml`(纯数据模板, 非执行器) | `tools/pipelines/README.md` |

## Per-category index files

| File | Category | Purpose | When to read |
|------|----------|---------|-------------|
| `_index-crypto.md` | crypto | crypto 工具契约条目(每工具 H3 条目: 用途/用法/输入/输出/exit code/when_not) | worker 被派发到加密识别/解码/哈希任务时 |
| `_index-static.md` | static | static 工具契约条目(同上模板) | worker 被派发到静态 triage 任务时 |
| `_index-ghidra.md` | ghidra | ghidra 工具契约条目(同上模板) | worker 被派发到函数级反汇编任务时 |
| `_index-dynamic.md` | dynamic | VM 动态工具契约条目(MCP 提供, 同上模板) | worker 被派发到动态调试任务时 |
| `_index-pipelines.md` | pipelines | pipelines 工具契约条目(同上模板) | worker 被派发到证据登记/报告任务时 |
| `_index-auxiliary.md` | auxiliary | auxiliary 工具契约条目(同上模板) | worker 需要哈希/文件元数据等小任务时 |

## Top-level tools files

| File | Category | Purpose | When to read |
|------|----------|---------|-------------|
| `_INDEX.yaml` | machine-contract | 工具机器索引(schema `tools-index/1`): name/category/capability/tier/cost_tier/input_output/when_not,由 `validate_index.py` 校验 | 需要机器可读的工具注册表/被 gate 调用时 |
| `README.md` | docs | 工具家说明: 结构规则(#340) + 分类结构 + 契约字段含义 + MD 格式规范 + 如何登记新工具 | 理解分类 / 登记 / 修改契约字段时 |
| `tool-search.py` | gate(meta) | `_INDEX.yaml` 确定性查询 CLI(零 LLM/零网络; 根层元工具例外, 见 README 结构规则) | 按能力标签/预算查工具时 |
| `validate_index.py` | gate(meta) | `_INDEX.yaml` 机器契约校验器(exit 0=通过 / 1=失败,可被 gate 调用; 根层元工具例外) | 校验索引、接入 gate 时 |

## tools/ scripts(按类目目录归位, #340)

| File | Category | Purpose | When to read |
|------|----------|---------|-------------|
| `crypto/crypto-tool.py` | crypto | 8 算法加解密/解码 CLI(chacha/xor-add/rolling-xor/lzss/lzma-raw/rsa-unpad/go-byte-transform/va-to-off) | 加密/编码/压缩层识别与试解时 |
| `auxiliary/audit_legacy_proven.py` | auxiliary | 审计 legacy PROVEN fact 状态 | 需要清理旧事实状态时 |
| `pipelines/build_evidence_index.py` | pipelines | 证据索引构建器(evidence/_index.json + _INDEX.md) | 证据落盘后登记索引时 |
| `auxiliary/capture_golden.py` | auxiliary | golden 用例采集 | 更新 golden fixtures 时 |
| `static/disasm_constant_check.py` | static | 反汇编常量 byte-exact 校验 | 校验反汇编断言时 |
| `auxiliary/measure_blind_coverage.py` | auxiliary | 盲验覆盖率测量 | 评估盲验覆盖时 |
| `auxiliary/measure_cold_start.py` | auxiliary | 冷启动测量 | 评估冷启动成本时 |
| `auxiliary/sanitize.py` | auxiliary | 样本内容 prompt 注入 sanitize(零宽/同形字/指令标记) | 样本派生文本喂给 LLM worker 前 |
| `ghidra/run_ghidra_postscript.py` | ghidra | analyzeHeadless 封装(调 5 件 postScript 工具) | 需要 headless 运行 Ghidra 工具时 |
| `_lib/lib_disasm.py` | shared-lib | 跨类目共享库: PE/capstone VA→offset 核心(不注册索引) | 新反汇编工具复用 VA→offset 时 |
