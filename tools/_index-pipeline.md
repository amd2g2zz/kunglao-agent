# pipeline 领域索引(工具层)
> 领域:证据索引/报告管线工具。worker 被派发到证据登记、索引构建、报告生成类任务时先读本文件,再按需加载。契约字段含义见 [README.md](README.md),机器契约见 [_INDEX.yaml](_INDEX.yaml)。
| 工具 | 契约(一行) | 何时读 / 何时不用 |
|---|---|---|
| `build-evidence-index` | `category: pipeline · capability: pipeline:evidence-index · tier: T1 · cost_tier: cheap · input: workspace 证据目录 → output: evidence/_index.json + _INDEX.md` | 证据落盘后需要登记索引时读; 纯分析不做登记时不用 |

<!-- 骨架: 每登记一个 pipeline 工具到 _INDEX.yaml,在此追加一行,格式同上。 -->
