# static 领域索引(工具层)
> 领域:静态识别/特征提取工具。worker 被派发到静态 triage(语言/编译器/加壳识别、字符串、签名)任务时先读本文件,再按需加载。契约字段含义见 [README.md](README.md),机器契约见 [_INDEX.yaml](_INDEX.yaml)。
| 工具 | 契约(一行) | 何时读 / 何时不用 |
|---|---|---|
| `die` | `category: static · capability: static:identify · tier: T1 · cost_tier: probe · input: 样本路径 → output: 语言/编译器/加壳识别 json` | 拿到新样本先做快速识别时读; 已确认加壳族/语言后不用 |

<!-- 骨架: 每登记一个 static 工具到 _INDEX.yaml,在此追加一行,格式同上。 -->
