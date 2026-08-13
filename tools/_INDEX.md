# tools/ Domain Index — progressive disclosure entry point

> Orchestrator: read this file once per round, pick a category, dispatch the worker; the worker reads `_index-<category>.md`, then loads `_INDEX.yaml` for the machine contract. Full per-category catalog below the category table.

## Category table

| Category | Index file | Tool shelf (examples) | Purpose |
|---|---|---|---|
| crypto | `_index-crypto.md` | chacha-string-layer | 加解密/编解码/哈希工具 |
| static | `_index-static.md` | die, floss, pefile | 静态识别/特征提取工具 |
| ghidra | `_index-ghidra.md` | ghidra-recon, ghidra-decompile-functions, ghidra-vtable-struct, ghidra-evidence-annotations, ghidra-scan-pointer | Ghidra 反汇编/函数级分析 |
| dynamic | `_index-dynamic.md` | x64dbg-remote, frida-remote | VM 动态调试/运行时分析 |
| pipeline | `_index-pipeline.md` | build-evidence-index | 证据索引/报告管线 |
| aux | `_index-aux.md` | file-hash, strings | 辅助/杂项工具 |

| Scenario | Category |
|---|---|
| 新样本快速识别(语言/编译器/加壳) | static |
| 加密/编码/哈希识别与解码 | crypto |
| 函数级反汇编 / 导入 / xref / 结构恢复 | ghidra |
| 运行时动态验证(单步/断点/hook, VM-only) | dynamic |
| 证据登记 / 索引构建 / 报告生成 | pipeline |
| 哈希 / 文件元数据 / 小杂务 | aux |

## Per-category index files

| File | Category | Purpose | When to read |
|------|----------|---------|-------------|
| `_index-crypto.md` | crypto | 加解密/编解码/哈希工具骨架 + 一行式契约示例 | worker 被派发到加密识别/解码/哈希任务时 |
| `_index-static.md` | static | 静态识别/特征提取工具骨架 + 一行式契约示例 | worker 被派发到静态 triage 任务时 |
| `_index-ghidra.md` | ghidra | Ghidra 反汇编/函数分析工具骨架 + 一行式契约示例 | worker 被派发到函数级反汇编任务时 |
| `_index-dynamic.md` | dynamic | VM 动态调试工具骨架 + 一行式契约示例 | worker 被派发到动态调试任务时 |
| `_index-pipeline.md` | pipeline | 证据索引/报告管线工具骨架 + 一行式契约示例 | worker 被派发到证据登记/报告任务时 |
| `_index-aux.md` | aux | 辅助/杂项工具骨架 + 一行式契约示例 | worker 需要哈希/文件元数据等小任务时 |

## Top-level tools files

| File | Category | Purpose | When to read |
|------|----------|---------|-------------|
| `_INDEX.yaml` | machine-contract | 工具机器索引(schema `tools-index/1`): name/category/capability/tier/cost_tier/input_output/when_not,由 `validate_index.py` 校验 | 需要机器可读的工具注册表/被 gate 调用时 |
| `README.md` | docs | 工具家说明: 分类结构 + 契约字段含义 + 如何登记新工具 | 理解分类 / 登记 / 修改契约字段时 |
| `validate_index.py` | gate | `_INDEX.yaml` 机器契约校验器(exit 0=通过 / 1=失败,可被 gate 调用) | 校验索引、接入 gate 时 |

## tools/ scripts

| File | Category | Purpose | When to read |
|------|----------|---------|-------------|
| `audit_legacy_proven.py` | aux | 审计 legacy PROVEN fact 状态 | 需要清理旧事实状态时 |
| `build_evidence_index.py` | pipeline | 证据索引构建器(evidence/_index.json + _INDEX.md) | 证据落盘后登记索引时 |
| `capture_golden.py` | aux | golden 用例采集 | 更新 golden fixtures 时 |
| `disasm_constant_check.py` | static | 反汇编常量 byte-exact 校验 | 校验反汇编断言时 |
| `measure_blind_coverage.py` | aux | 盲验覆盖率测量 | 评估盲验覆盖时 |
| `measure_cold_start.py` | aux | 冷启动测量 | 评估冷启动成本时 |
| `ghidra/run_ghidra_postscript.py` | ghidra | analyzeHeadless 封装(调 5 件 postScript 工具) | 需要 headless 运行 Ghidra 工具时 |
