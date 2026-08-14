# tools/static — 静态分析工具家

本目录是 `static` 类目的工具家: 存放纯本地静态分析 CLI — PE 解析、字符串与熵提取、syscall/栈字符串/覆盖区扫描、反汇编比对与清单校验等。当前登记 16 个工具(见 `tools/_INDEX.yaml`)。

## 与索引文档的关系

worker 先读 `tools/_index-static.md`(16 个工具的 6 段契约条目: 用途/用法/输入/输出/exit code/when_not, 用法可直接复制); 本 README 只说明家内文件分工与吸收沿革。机器契约见 `tools/_INDEX.yaml`。

## 已吸收工具 (issue #278 PR-1b, 6 个零依赖 CLI)

| 工具 | 来源脚本 | 一句话契约 |
|---|---|---|
| `extract-syscalls.py` | `2026-06-10/scripts/extract_syscalls.py` | x64 syscall stub 提取(`mov eax, imm; syscall` / `mov r10, rcx` 回溯 + NT 名称表) |
| `stack-strings.py` | `2026-06-10/scripts/check_stack_strings.py` | `mov byte/dword [rsp+disp], imm` 栈构造字符串重建 |
| `binary-sweep.py` | `2026-07-01/scripts/binary_sweep.py` | URL/IPv4/域名/自定义字节正则扫描, 带文件偏移 |
| `strings-classify.py` | `2026-06-10/scripts/analyze_decrypted.py` + `2026-07-01/scripts/floss_filter.py` | 字符串熵/可打印/可解码(base64/hex)分类 |
| `go-buildinfo-carve.py` | `2026-06-10/evidence/pe-analysis/verify_go_buildinfo.py` + `2026-06-10/scripts/gap_determinative.py` | Go buildinfo 定位与解析(版本/path/deps) |
| `call-site-args.py` | `2026-06-10/scripts/analysis/build_xpsplog_payload_evidence.py` + `2026-06-10/scripts/analysis/qiling_npwzwmc64_realargs_native_probe.py` | 反汇编文本调用点参数提取(x64 寄存器/栈槽/x86 push) |

`common.py` 是共享 CLI 管道(#277 契约: 0/1/2 三态退出码、`--json`、`--reproduce` field=value、错误带指引), 不是工具, 不登记索引。

## 已吸收工具 (issue #278 PR-1c)

| 文件 | 工具 | 职责 |
|---|---|---|
| `pe_analyze.py` | `pe-analyze` | PE trunk 解析: headers/sections/imports/exports/resources/overlay/pdb/tls/signature 子命令 |
| `overlay_scan.py` | `overlay-scan` | 覆盖区 3-in-1: `--mode reloc\|true\|mz`(reloc 表 / true-overlay / MZ 内嵌 PE) |
| `disasm_dump.py` | `disasm-dump` | 指定 RVA/VA 的 capstone 指令清单(复用 `tools/_lib/lib_disasm.py` 的 VA→offset 核心) |
| `shellcode_scan.py` | `shellcode-scan` | shellcode blob 检测: 入口反汇编/代码区扫描/序言/PEB 访问/字符串 |
| `die_probe.py` | `die-probe` | DIE 5-call merge 探测包装(die 缺失 exit 2 + 安装指引) |

其余登记工具: `yara-scan.py` + `yara-gen.py`(issue #313, 吸收 findcrypt-yara 规则资产至 `yara-rules/`)、`c_normalize.py` + `opaque_pred.py`(issue #306, 反编译 C 后处理)、`disasm_constant_check.py`(issue #284; #340 起由 tools/ 根层归位本目录)。

## 共享模块(#340 合并)

`common.py` 是 static 类目的**唯一**共享模块(#340 结构规则: 一类目一个共享模块)。#340 将原双模块合并为一个并保留全部公共面:

- CLI 管道(原 `common.py`): `error`/`add_common_flags`/`read_bytes`/`read_text`/`parse_int`/`sha256`/`parse_line`/`report`/`negative` + `EXIT_*`/`L1_FIELD_RE`(#277 契约)。
- 字节扫描助手(原 `_common.py`, #278 PR-1c): `EXE_SIGNATURES`/`X64_PROLOG_PATTERNS`/`PEB_ACCESS_PATTERNS`/`find_all`/`signature_hits`/`ascii_strings`/`x64_prolog_offsets`/`byte_entropy`/`uniform_variance`/`scan_valid_pclntab`。

`tools/_lib/lib_disasm.py`(跨类目共享库单点)提供 PE/capstone VA→offset 核心, 不在本目录。

lzma-raw 不再单独吸收: `tools/crypto/crypto-tool.py` 的 `lzma-raw` 子命令(`algorithms.lzma_raw_decompress`, dict_size/lc/lp/pb/size 全参数化)已覆盖同能力, 避免重复。

## 契约要点(#277)

- 全部参数化、只读幂等、三态退出码: 0 成功 / 1 负发现(跑了无结果) / 2 错误(坏参数/不可读输入, 带指引)。
- `--json` 默认输出单 JSON 对象 + `--reproduce` field=value 行(kunglao L1 机械门)。
- 每工具的用法/exit code 细则以 `tools/_index-static.md` 契约条目为准。
