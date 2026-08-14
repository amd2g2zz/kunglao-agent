# tools/static — 静态分析工具家

存放静态分析工具：PE/ELF 解析（pefile）、字符串与熵提取、FLOSS 解码、DIE 打包器识别、
反汇编比对（disasm_constant_check）、代码清单校验等纯本地静态分析。

issue #278 PR-1b 起，从样本工作区脚本积累中吸收 6 个零依赖（纯标准库）CLI 至此：

| 工具 | 来源脚本 | 一句话契约 |
|---|---|---|
| `extract-syscalls.py` | `2026-06-10/scripts/extract_syscalls.py` | x64 syscall stub 提取（`mov eax, imm; syscall` / `mov r10, rcx` 回溯 + NT 名称表） |
| `stack-strings.py` | `2026-06-10/scripts/check_stack_strings.py` | `mov byte/dword [rsp+disp], imm` 栈构造字符串重建 |
| `binary-sweep.py` | `2026-07-01/scripts/binary_sweep.py` | URL/IPv4/域名/自定义字节正则扫描，带文件偏移 |
| `strings-classify.py` | `2026-06-10/scripts/analyze_decrypted.py` + `2026-07-01/scripts/floss_filter.py` | 字符串熵/可打印/可解码（base64/hex）分类 |
| `go-buildinfo-carve.py` | `2026-06-10/evidence/pe-analysis/verify_go_buildinfo.py` + `2026-06-10/scripts/gap_determinative.py` | Go buildinfo 定位与解析（版本/path/deps） |
| `call-site-args.py` | `2026-06-10/scripts/analysis/build_xpsplog_payload_evidence.py` + `2026-06-10/scripts/analysis/qiling_npwzwmc64_realargs_native_probe.py` | 反汇编文本调用点参数提取（x64 寄存器/栈槽/x86 push） |

`common.py` 是共享 CLI 管道（#277 契约：0/1/2 三态退出码、`--json`、`--reproduce`
field=value、错误带指引），不是工具，不登记索引。

lzma-raw 不再单独吸收：`tools/crypto/crypto-tool.py` 的 `lzma-raw` 子命令
（`algorithms.lzma_raw_decompress`，dict_size/lc/lp/pb/size 全参数化）已覆盖同
能力，避免重复。
