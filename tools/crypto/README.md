# tools/crypto — 加密 / 哈希工具家

本目录是 `crypto` 类目的工具家: 存放密码学相关工具(加解密/解码/哈希例程的本地 CLI)。当前含 1 个注册工具 + 1 个算法库:

| 文件 | 工具(id) | 职责 |
|---|---|---|
| `crypto-tool.py` | `crypto-tool` | 8 算法加解密/解码 CLI: chacha / xor-add / rolling-xor / lzss / lzma-raw / rsa-unpad / go-byte-transform / va-to-off(issue #285 吸收) |
| `algorithms.py` | —(被 crypto-tool 导入) | 算法实现库(chacha/lzma_raw_decompress 等, 全参数化), 不是 CLI, 不登记索引 |
| `__init__.py` | — | 包标记 |

## 与索引文档的关系

worker 先读 `tools/_index-crypto.md`(`crypto-tool` 的 6 段契约条目: 用途/用法/输入/输出/exit code/when_not, 用法可直接复制); 本 README 只说明家内文件分工与沿革。机器契约见 `tools/_INDEX.yaml`。

## 契约要点

- exit code 三态(#277): 0 成功 / 1 负发现(试解未命中) / 2 错误(带指引)。
- `--self-check` 子命令校验环境依赖, 试解前先跑。
- `--json` 单 JSON 对象输出; `--reproduce` 输出 field=value 行(kunglao L1 机械门)。
- lzma-raw 不再单独吸收脚本: `crypto-tool.py lzma-raw` 子命令(dict_size/lc/lp/pb/size 全参数化)已覆盖同能力, 避免重复。
