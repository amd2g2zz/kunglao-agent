# ghidra 领域索引(工具层)

> 领域: Ghidra 反汇编/函数级分析。worker 被派发到函数反汇编、导入/xref 导出、结构恢复类任务时先读本文件, 再按需加载。契约字段含义见 [README.md](README.md), 机器契约见 [_INDEX.yaml](_INDEX.yaml)。5 个工具统一经 `tools/ghidra/run_ghidra_postscript.py` 调用(analyzeHeadless 封装, `--key=value` 转发给 postScript)。

## 工具清单

| 工具 | 用途(一句话) | 何时读 / 何时不用 |
|---|---|---|
| `ghidra-recon` | 函数级静态侦察(导入/导出/字符串/可疑 API/Go 特征) | 需要函数级静态侦察时读; 仅单函数反汇编用 ghidra-decompile-functions |
| `ghidra-decompile-functions` | 定点反编译 + 反汇编窗口 + 字符串 xref(可选 --context 增上下文) | 需要定点反汇编+反编译时读; 批量全量反汇编不是本工具职责 |
| `ghidra-vtable-struct` | vtable/回调表结构恢复 | 需要恢复 vtable/回调表结构时读; 无明确 vtable 地址或纯文本任务不用 |
| `ghidra-evidence-annotations` | TSV 证据标注写回/校验(fail-closed) | 需要把证据 TSV 写回/校验 Ghidra 工程时读; 无证据 TSV 不用 |
| `ghidra-scan-pointer` | xref 查询 / 指向某范围的 8-byte 指针扫描 | 需要查地址引用或扫描指针时读; 仅字符串定位用 ghidra-decompile-functions |

## 契约条目

### ghidra-recon

- **用途**: 函数级静态侦察: 导入/导出/字符串/可疑 API 调用/focus functions/Go 特征打包成 JSON。
- **用法**:
  ```bash
  python tools/ghidra/run_ghidra_postscript.py --tool ghidra-recon --binary <abs-sample> --out <abs-output.json>
  ```
- **输入**: 样本 + `--search-terms`/`--expected-exports`/`--sha256`/`--sha1`(经 `--key=value` 转发)。
- **输出**: JSON(meta/imports/exports/functions/strings_of_interest/suspicious_api_calls/focus_functions/go/findings)。
- **exit code**: 0 成功 / 2 错误(GHIDRA_HOME 缺失 / analyzeHeadless.bat 不存在 / 参数错误 / postScript 失败, 带指引)。
- **when_not**: 仅需单函数反汇编时不用, 用 ghidra-decompile-functions。

### ghidra-decompile-functions

- **用途**: 定点反编译: 每目标输出反编译 C + 反汇编窗口 + 字符串 xref; `--context` 增 caller/callee 片段 + xref 串 + 已恢复命名(ghidra_context.v1)。
- **用法**:
  ```bash
  python tools/ghidra/run_ghidra_postscript.py --tool ghidra-decompile-functions --binary <abs-sample> --out <abs-output.json> --addresses 0x401000,0x402000
  ```
- **输入**: 样本 + `--addresses`/`--strings`/`--window`/`--context`。
- **输出**: JSON(per-target decompiled C + disasm window + string xrefs; `--context` 增 caller/callee ~10 行片段 + xref 串 + 已恢复命名)。
- **exit code**: 0 成功 / 2 错误(GHIDRA_HOME 缺失 / 参数错误 / postScript 失败)。
- **when_not**: 批量全量反汇编不用; 需要 vtable 恢复时用 ghidra-vtable-struct。

### ghidra-vtable-struct

- **用途**: 从 vtable 地址恢复槽位表与 function fields, 可选落结构/标签。
- **用法**:
  ```bash
  python tools/ghidra/run_ghidra_postscript.py --tool ghidra-vtable-struct --binary <abs-sample> --out <abs-output.json> --address 0x140001000
  ```
- **输入**: 样本 + `--address`/`--name`/`--class`/`--apply`。
- **输出**: JSON(vtable slot 表 + function fields, 可选落结构/标签)。
- **exit code**: 0 成功 / 2 错误(GHIDRA_HOME 缺失 / 参数错误 / postScript 失败)。
- **when_not**: 无明确 vtable 地址或纯文本任务不用。

### ghidra-evidence-annotations

- **用途**: 把 TSV 证据标注应用/校验回 Ghidra 工程; verify 失败抛错 fail-closed。
- **用法**:
  ```bash
  python tools/ghidra/run_ghidra_postscript.py --tool ghidra-evidence-annotations --binary <abs-sample> --out <abs-output.json> --mode apply --tsv <证据.tsv>
  ```
- **输入**: 样本 + `--mode apply|verify` + `--tsv <路径>`。
- **输出**: JSON(annotation 应用/校验摘要)。
- **exit code**: 0 成功 / 2 错误(GHIDRA_HOME 缺失 / 参数错误 / verify 失败 fail-closed)。
- **when_not**: 无证据 TSV 需要写回/校验时不用。

### ghidra-scan-pointer

- **用途**: xref 查询或扫描指向某范围的全部 raw 8-byte 指针。
- **用法**:
  ```bash
  python tools/ghidra/run_ghidra_postscript.py --tool ghidra-scan-pointer --binary <abs-sample> --out <abs-output.json> --mode xref --addresses 0x401000
  ```
- **输入**: 样本 + `--mode xref|window`(xref: `--addresses`/`--bytes`; window: `--center`/`--window`)。
- **输出**: JSON(xref/raw 8-byte 指针扫描命中)。
- **exit code**: 0 成功 / 2 错误(GHIDRA_HOME 缺失 / 参数错误 / postScript 失败)。
- **when_not**: 仅字符串定位不用, 用 ghidra-decompile-functions。
