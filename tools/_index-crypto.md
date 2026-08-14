# crypto 领域索引(工具层)

> 领域: 加解密/编解码/哈希工具。worker 被派发到加密识别/解码/哈希类任务时先读本文件, 再按需加载。契约字段含义见 [README.md](README.md), 机器契约见 [_INDEX.yaml](_INDEX.yaml)。

## 工具清单

| 工具 | 用途(一句话) | 何时读 / 何时不用 |
|---|---|---|
| `crypto-tool` | 8 算法加解密/解码 CLI(chacha/xor-add/rolling-xor/lzss/lzma-raw/rsa-unpad/go-byte-transform/va-to-off) | 识别到加密/编码/压缩层时读; 非本 8 算法族方案不用 |

## 契约条目

### crypto-tool

- **用途**: 对密文字节串执行 8 算法族之一(chacha/xor-add/rolling-xor/lzss/lzma-raw/rsa-unpad/go-byte-transform/va-to-off)的解密/变换, 输出明文层。
- **用法**:
  ```bash
  python tools/crypto/crypto-tool.py chacha --in <密文文件> --key <32字节hex> --nonce <12字节hex>
  ```
- **输入**: 密文字节串(`--in <PATH>` 或 `--in-hex <HEX>`) + 子命令(8 算法之一; chacha 需 `--key`/`--nonce`); 可选 `--json` / `--reproduce` / `--self-check`。
- **输出**: 明文/变换后字节(默认文本, `--json` 单 JSON 对象; `--reproduce` 输出 field=value 行供 L1 机械门)。
- **exit code**: 0 成功 / 1 负发现(试解未命中) / 2 错误(用法或环境缺失, 带指引)。
- **when_not**: 非本 8 算法族的加密方案不用; 先用 `--self-check` 校验环境(与 _INDEX.yaml when_not 一致)。
