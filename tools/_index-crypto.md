# crypto 领域索引(工具层)
> 领域:加解密/编解码/哈希工具。worker 被派发到加密识别/解码/哈希类任务时先读本文件,再按需加载。契约字段含义见 [README.md](README.md),机器契约见 [_INDEX.yaml](_INDEX.yaml)。
| 工具 | 契约(一行) | 何时读 / 何时不用 |
|---|---|---|
| `crypto-tool` | `category: crypto · capability: crypto:decode · tier: T1 · cost_tier: cheap · input: 密文字节串 + 子命令(chacha/xor-add/rolling-xor/lzss/lzma-raw/rsa-unpad/go-byte-transform/va-to-off) → output: 明文/变换字节` | 识别到加密/编码/压缩层时先读, 按算法选子命令试解; 非本 8 算法族方案不用(先 `--self-check` 校验环境) |

<!-- 骨架: 每登记一个 crypto 工具到 _INDEX.yaml,在此追加一行,格式同上。 -->
