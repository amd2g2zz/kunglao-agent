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

## 已吸收工具 (issue #278 PR-1c)

| 文件 | 工具 | 职责 |
|---|---|---|
| `pe_analyze.py` | `pe-analyze` | PE trunk 解析: headers/sections/imports/exports/resources/overlay/pdb/tls/signature 子命令 |
| `overlay_scan.py` | `overlay-scan` | 覆盖区 3-in-1: `--mode reloc|true|mz` (reloc 表 / true-overlay / MZ 内嵌 PE) |
| `disasm_dump.py` | `disasm-dump` | 指定 RVA/VA 的 capstone 指令清单 (复用 `tools/lib_disasm.py` 的 VA→offset 核心) |
| `shellcode_scan.py` | `shellcode-scan` | shellcode blob 检测: 入口反汇编/代码区扫描/序言/PEB 访问/字符串 |
| `die_probe.py` | `die-probe` | DIE 5-call merge 探测包装 (die 缺失 exit 2 + 安装指引) |
| `_common.py` | — | 共享字节扫描助手(签名/字符串/序言/熵/pclntab), 无副作用可导入 |

契约(#277): 全部参数化、只读幂等、三态退出码(0 成功 / 1 负发现 / 2 错误)、
`--json` 默认输出 + `--reproduce` field=value 行(kunglao L1 机械门)。
