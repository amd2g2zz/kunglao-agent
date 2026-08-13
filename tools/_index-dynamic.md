# dynamic 领域索引(工具层)
> 领域:VM 动态调试/运行时分析。worker 被派发到动态调试(x64dbg/Frida)类任务时先读本文件,再按需加载。动态工具一律 VM-only(192.168.20.128)。契约字段含义见 [README.md](README.md),机器契约见 [_INDEX.yaml](_INDEX.yaml)。
| 工具 | 契约(一行) | 何时读 / 何时不用 |
|---|---|---|
| `x64dbg-remote` | `category: dynamic · capability: dynamic:debug · tier: T3 · cost_tier: deep · input: VM 进程 attach → output: 运行时寄存器/内存/调用栈` | 需要单步/断点动态验证时读; 纯静态可解的问题不用(VM 成本高) |

<!-- 骨架: 每登记一个 dynamic 工具到 _INDEX.yaml,在此追加一行,格式同上。 -->
