# aux 领域索引(工具层)
> 领域:辅助/杂项工具(哈希、编码、文件元数据)。worker 被派发到辅助性小任务时先读本文件,再按需加载。契约字段含义见 [README.md](README.md),机器契约见 [_INDEX.yaml](_INDEX.yaml)。
| 工具 | 契约(一行) | 何时读 / 何时不用 |
|---|---|---|
| `file-hash` | `category: aux · capability: aux:hash · tier: T1 · cost_tier: probe · input: 文件路径 → output: sha256/md5/size` | 需要样本哈希/尺寸元数据时读; 哈希已由更上层工具给出时不用 |
| `audit-legacy-proven` | `category: aux · capability: aux:proven-audit · tier: T1 · cost_tier: cheap · input: workspace(claim-register.yaml + facts/_INDEX.md) → output: legacy PROVEN 审计 json/摘要` | 清理旧 PROVEN claim 状态时读; 无 legacy PROVEN 需审计时不用 |
| `capture-golden` | `category: aux · capability: aux:golden-capture · tier: T1 · cost_tier: cheap · input: CASES 清单(合成工作区) → output: tests/fixtures/golden/{manifest.yaml, F-NN/}` | 契约变更需重采 golden 基线时读; 常规分析不用 |
| `measure-blind-coverage` | `category: aux · capability: aux:blind-coverage · tier: T1 · cost_tier: cheap · input: workspace(claim-register.yaml + facts verifier_sign_off) → output: BLIND 覆盖率 json` | 评估盲验覆盖时读; 无需评估时不用 |
| `measure-cold-start` | `category: aux · capability: aux:cold-start-metrics · tier: T1 · cost_tier: probe · input: workspace 状态文件清单 → output: docs/baselines/cold-start-tokens.json` | 测量冷启动 token 基线时读; 非基线测量不用 |
| `sanitize-text` | `category: aux · capability: aux:sanitize · tier: T1 · cost_tier: probe · input: 样本派生文本(--in/标准输入) → output: 净化文本或 JSON(zwx/homoglyph/marker 计数 + suspicious + sha256)` | 样本派生文本喂给 LLM worker 前读; 纯分析不产出供 LLM 消费的文本时不用 |

<!-- 骨架: 每登记一个 aux 工具到 _INDEX.yaml,在此追加一行,格式同上。 -->
