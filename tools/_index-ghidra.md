# ghidra 领域索引(工具层)
> 领域:Ghidra 反汇编/函数级分析。worker 被派发到函数反汇编、导入/xref 导出、结构恢复类任务时先读本文件,再按需加载。契约字段含义见 [README.md](README.md),机器契约见 [_INDEX.yaml](_INDEX.yaml)。
| 工具 | 契约(一行) | 何时读 / 何时不用 |
|---|---|---|
| `ghidra-recon` | `category: ghidra · capability: ghidra:recon · tier: T1 · cost_tier: deep · input: 样本 + --search-terms/--expected-exports → output: JSON(imports/exports/functions/strings_of_interest/suspicious_api_calls/focus_functions/go/findings)` | 需要函数级静态侦察(导入/导出/字符串/可疑 API/Go garble)时读; 仅需单函数反汇编用 ghidra-decompile-functions |
| `ghidra-decompile-functions` | `category: ghidra · capability: ghidra:decompile · tier: T1 · cost_tier: deep · input: 样本 + --addresses/--strings/--window/--context → output: JSON(per-target decompiled C + disasm window + string xrefs; --context 增 caller/callee ~10 行片段 + xref 串 + 已恢复命名, ghidra_context.v1)` | 需要定点反汇编+反汇编窗口或字符串定位时读; 需要 LLM 上下文配方(caller/callee 片段/xref 串/已恢复命名)时加 --context; 批量全量反汇编不是本工具职责 |
| `ghidra-vtable-struct` | `category: ghidra · capability: ghidra:vtable · tier: T1 · cost_tier: cheap · input: 样本 + --address/--name/--class/--apply → output: JSON(vtable slot 表 + function fields, 可选落结构/标签)` | 需要恢复 vtable/回调表结构时读; 无明确 vtable 地址或纯文本任务不用 |
| `ghidra-evidence-annotations` | `category: ghidra · capability: ghidra:annotate · tier: T1 · cost_tier: cheap · input: 样本 + --mode apply\|verify + --tsv → output: JSON(annotation 应用/校验摘要, verify 失败抛错 fail-closed)` | 需要把 TSV 证据标注写回/校验 Ghidra 工程时读; 无证据 TSV 不用 |
| `ghidra-scan-pointer` | `category: ghidra · capability: ghidra:xref-scan · tier: T1 · cost_tier: deep · input: 样本 + --mode xref\|window(--addresses/--center) → output: JSON(xref/raw 8-byte 指针扫描命中)` | 需要查地址引用或扫描指向某范围的全部指针时读; 仅字符串定位用 ghidra-decompile-functions |
| `ghidra-headless` | `category: ghidra · capability: ghidra:disasm · tier: T1 · cost_tier: deep · input: 样本路径 → output: 函数列表/导入/xref json` | 需要函数级反汇编或批量导出时读; 仅做快速识别时用 static 域工具即可 |

<!-- 骨架: 每登记一个 ghidra 工具到 _INDEX.yaml,在此追加一行,格式同上。 -->
