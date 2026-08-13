# aux 领域索引(工具层)
> 领域:辅助/杂项工具(哈希、编码、文件元数据)。worker 被派发到辅助性小任务时先读本文件,再按需加载。契约字段含义见 [README.md](README.md),机器契约见 [_INDEX.yaml](_INDEX.yaml)。
| 工具 | 契约(一行) | 何时读 / 何时不用 |
|---|---|---|
| `file-hash` | `category: aux · capability: aux:hash · tier: T1 · cost_tier: probe · input: 文件路径 → output: sha256/md5/size` | 需要样本哈希/尺寸元数据时读; 哈希已由更上层工具给出时不用 |

<!-- 骨架: 每登记一个 aux 工具到 _INDEX.yaml,在此追加一行,格式同上。 -->
