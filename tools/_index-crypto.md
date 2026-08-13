# crypto 领域索引(工具层)
> 领域:加解密/编解码/哈希工具。worker 被派发到加密识别/解码/哈希类任务时先读本文件,再按需加载。契约字段含义见 [README.md](README.md),机器契约见 [_INDEX.yaml](_INDEX.yaml)。
| 工具 | 契约(一行) | 何时读 / 何时不用 |
|---|---|---|
| `chacha-string-layer` | `category: crypto · capability: crypto:decode · tier: T1 · cost_tier: cheap · input: 密文字节串 → output: 明文层` | 识别到 ChaCha20 字符串加密层时读; 非 ChaCha 流加密不用 |

<!-- 骨架: 每登记一个 crypto 工具到 _INDEX.yaml,在此追加一行,格式同上。 -->
