# ghidra 领域索引(工具层)
> 领域:Ghidra 反汇编/函数级分析。worker 被派发到函数反汇编、导入/xref 导出、结构恢复类任务时先读本文件,再按需加载。契约字段含义见 [README.md](README.md),机器契约见 [_INDEX.yaml](_INDEX.yaml)。
| 工具 | 契约(一行) | 何时读 / 何时不用 |
|---|---|---|
| `ghidra-headless` | `category: ghidra · capability: ghidra:disasm · tier: T1 · cost_tier: deep · input: 样本路径 → output: 函数列表/导入/xref json` | 需要函数级反汇编或批量导出时读; 仅做快速识别时用 static 域工具即可 |

<!-- 骨架: 每登记一个 ghidra 工具到 _INDEX.yaml,在此追加一行,格式同上。 -->
