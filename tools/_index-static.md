# static 领域索引(工具层)

> 领域: 静态识别/特征提取工具。worker 被派发到静态 triage(语言/编译器/加壳识别、字符串、签名、反汇编校验)任务时先读本文件, 再按需加载。契约字段含义见 [README.md](README.md), 机器契约见 [_INDEX.yaml](_INDEX.yaml)。

## 工具清单

| 工具 | 用途(一句话) | 何时读 / 何时不用 |
|---|---|---|
| `die-probe` | DIE 5-call merge 探测(语言/编译器/加壳/熵/资源) | 需要 DIE 结构化多面探测时读; DIE 未安装时不用 |
| `pe-analyze` | PE 表解析(headers/sections/imports/exports/resources/overlay/pdb/tls/signature) | 需要 PE 单域解析时读; 需要反汇编时用 disasm-dump |
| `overlay-scan` | 覆盖区 3-in-1 表征(reloc/true/mz) | 怀疑覆盖区藏 reloc 表/内嵌 PE 时读; 无覆盖区时不用 |
| `disasm-dump` | 指定 RVA/VA 的 capstone 指令清单 | 需要字节锚定指令清单时读; 函数级语义用 ghidra-recon |
| `shellcode-scan` | shellcode/blob 检测(入口反汇编/序言/PEB/字符串) | 怀疑 blob/解密层是 shellcode 时读; 常规 PE 函数分析时不用 |
| `disasm-constant-check` | 反汇编常量 byte-exact 校验(VA 锚点) | 校验反汇编常量断言时读; 无二进制样本时不用 |
| `extract-syscalls` | x64 syscall stub 提取(编号/名称) | 扫描 syscall stub 编号/名称时读; 非 syscall stub 任务不用 |
| `stack-strings` | `[rsp+disp]` 栈构造字符串重建 | 检测栈字符串构造模式时读; 无该模式时不用 |
| `binary-sweep` | 字节级 URL/IP/域名/自定义正则扫描 | 直接字节扫描模式时读; 需节表感知提取时用 die/floss 流程 |
| `strings-classify` | 字符串熵/可打印/可解码分类 + inventory | 字符串熵与 base64/hex 可解码分类时读; 仅枚举字符串用 floss |
| `go-buildinfo-carve` | Go buildinfo blob 定位与解析 | 提取 Go 构建信息时读; 非 Go 样本不用(先 die 确认语言) |
| `call-site-args` | 反汇编文本调用点参数提取(x64/x86) | 从反汇编文本提取调用点参数时读; 需精确数据流用 ghidra-recon/模拟执行 |
| `c-normalize` | 反编译 C 规范化(modulo 惯用法/死赋值) | worker 读 Ghidra 反编译 C 前先规范化时读; 语义反混淆用 opaque-pred |
| `opaque-pred` | 不透明谓词/MBA 等价判定(z3) | 静态消解不透明谓词/MBA 等价证明时读; z3 未装或非表达式任务不用 |
| `yara-scan` | YARA 规则扫描(内置 crypto-tables) | 规则式字节扫描(家族/IOC 证据)时读; yara-python 缺失不用 |
| `yara-gen` | 从分析发现生成 YARA 规则文本 | 从 hex/string 特征生成检测规则时读; 无规则生成需求时不用 |

## 契约条目

### die-probe

- **用途**: 对 PE 样本执行 DIE 5-call merge 探测, 输出语言/编译器/加壳/熵/资源的结构化识别结果。
- **用法**:
  ```bash
  python tools/static/die_probe.py --binary <样本PE> --die <diec.exe路径>
  ```
- **输入**: 样本 PE(`--binary`, 必填) + DIE 可执行文件(`--die` 或 `$KUNGLAO_DIE` 或 PATH 上的 diec)。
- **输出**: DIE 5-call merge JSON(`--json` 默认; `--reproduce` 输出 field=value 行)。
- **exit code**: 0 成功 / 1 全部 5 次 DIE 调用失败 / 2 错误(die 缺失带安装指引 / 参数错误)。
- **when_not**: DIE 未安装且不允许安装时不用。

### pe-analyze

- **用途**: PE 单域解析: headers/sections/imports/exports/resources/overlay/pdb/tls/signature 子命令。
- **用法**:
  ```bash
  python tools/static/pe_analyze.py --binary <样本PE> imports
  ```
- **输入**: 样本 PE(`--binary`, 必填) + 子命令(headers/sections/imports/exports/resources/overlay/pdb/tls/signature, 缺省 all)。
- **输出**: 对应 PE 表/数据 JSON + `--reproduce` field=value 行。
- **exit code**: 0 成功 / 1 负发现(子命令无内容) / 2 错误。
- **when_not**: 需要指令级反汇编或函数级视图时不用, 用 disasm-dump / ghidra-recon。

### overlay-scan

- **用途**: PE 覆盖区(overlay)3-in-1 表征: reloc 表 / true-overlay / MZ 内嵌 PE。
- **用法**:
  ```bash
  python tools/static/overlay_scan.py --binary <样本PE> --mode all
  ```
- **输入**: 样本 PE(`--binary`, 必填) + `--mode reloc|true|mz|all`。
- **输出**: 覆盖区表征 JSON(reloc 表/熵/Go 证据/内嵌 PE 命中)。
- **exit code**: 0 正发现 / 1 负发现(无覆盖区证据) / 2 错误。
- **when_not**: 无 PE 覆盖区(overlay)或无内嵌载荷怀疑时不用。

### disasm-dump

- **用途**: 指定 RVA/VA 的 capstone 指令清单(VA→文件偏移复用 tools/lib_disasm.py)。
- **用法**:
  ```bash
  python tools/static/disasm_dump.py --binary <样本PE> --rvas 0x1000,0x2000
  ```
- **输入**: 样本 PE(`--binary`, 必填) + `--rvas`/`--vas` 地址列表; 可选 `--prologs`/`--strings`/`--length`。
- **输出**: 每址 capstone 指令清单 JSON。
- **exit code**: 0 全部成功 / 1 部分地址失败 / 2 错误。
- **when_not**: 需要函数级语义/反编译时不用, 用 ghidra-recon / ghidra-decompile-functions。

### shellcode-scan

- **用途**: shellcode/blob 检测: 入口反汇编/代码区扫描/序言/PEB 访问/字符串。
- **用法**:
  ```bash
  python tools/static/shellcode_scan.py --binary <blob|PE> --scan --entry 0x0
  ```
- **输入**: 二进制 blob/PE(`--binary`, 必填) + `--scan`/`--entry`/`--prologs`/`--peb`/`--strings`。
- **输出**: shellcode 候选区域 + 特征 JSON(PEB 访问/序言/字符串/入口反汇编)。
- **exit code**: 0 有命中 / 1 无命中 / 2 错误。
- **when_not**: 非 shellcode/blob 检测任务不用。

### disasm-constant-check

- **用途**: 对 fact/report 代码清单做 byte-exact 断言校验(VA 锚点)。
- **用法**:
  ```bash
  python tools/disasm_constant_check.py --binary <样本PE> --fact <facts/F-NN.md>
  ```
- **输入**: fact/report 代码清单(`--fact` 或 `--report`+`--reference`) + PE 二进制(`--binary`, 必填)。
- **输出**: byte-exact 断言校验 JSON(ok/mismatches/errors/skipped)。
- **exit code**: 0 全部断言 ok / 1 存在 mismatch / 2 错误。
- **when_not**: 无需 VA 锚点常量校验或没有二进制样本时不用。

### extract-syscalls

- **用途**: x64 syscall stub 提取(`mov eax, imm; syscall` / `mov r10, rcx` 回溯 + NT 名称表)。
- **用法**:
  ```bash
  python tools/static/extract-syscalls.py --in <样本> --mode bin
  ```
- **输入**: 样本字节(`--in` + `--mode bin`)或反汇编文本(`--mode text`); 可选 `--no-names`/`--max-back`。
- **输出**: syscall stub 清单(location/number/name) + `--reproduce` field=value 行。
- **exit code**: 0 成功 / 1 负发现(无 stub) / 2 错误。
- **when_not**: 非 x64 syscall stub 扫描任务时不用。

### stack-strings

- **用途**: `mov byte/dword [rsp+disp], imm` 栈构造字符串重建。
- **用法**:
  ```bash
  python tools/static/stack-strings.py --in <样本> --start 0x0 --end 0x1000
  ```
- **输入**: 样本字节(`--in`) + `--start`/`--end` 区间; 可选 `--min-len`/`--dword`。
- **输出**: `[rsp+disp]` 栈构造字符串清单(slot/value/writes)。
- **exit code**: 0 成功 / 1 负发现(无命中) / 2 错误(区间非法等)。
- **when_not**: 无 mov byte/dword [rsp+disp] 栈写入模式时不用。

### binary-sweep

- **用途**: 字节级模式扫描: URL/IPv4/域名或自定义字节正则, 带文件偏移。
- **用法**:
  ```bash
  python tools/static/binary-sweep.py --in <样本> --kind all
  ```
- **输入**: 样本字节(`--in`) + `--kind url|ipv4|domain|all` 或 `--pattern <regex>`; 可选 `--max`。
- **输出**: 字节级模式命中清单(kind/offset/value)。
- **exit code**: 0 成功 / 1 负发现(无命中) / 2 错误(pattern 非法等)。
- **when_not**: 需要 PE 节表感知的结构化字符串提取时不用, 用 die/floss 流程。

### strings-classify

- **用途**: 字符串熵/可打印/可解码(base64/hex)分类 + inventory 统计。
- **用法**:
  ```bash
  python tools/static/strings-classify.py --in <样本> --encoding both
  ```
- **输入**: 样本字节(`--in`) + `--min-len`/`--encoding ascii|utf16le|both`。
- **输出**: 字符串分类清单(entropy/printable_ratio/base64/hex) + inventory 统计。
- **exit code**: 0 成功 / 1 负发现(无字符串) / 2 错误。
- **when_not**: 已用 floss 全量提取且无需熵/可解码分类时不用。

### go-buildinfo-carve

- **用途**: Go buildinfo blob 定位与解析(go 版本/path/mod 计数/dep 计数/size)。
- **用法**:
  ```bash
  python tools/static/go-buildinfo-carve.py --in <样本> --window 50000
  ```
- **输入**: 样本字节(`--in`) + `--window`/`--zero-run` 参数。
- **输出**: Go buildinfo blob 清单(offset/go_version/path/mod_count/dep_count/size)。
- **exit code**: 0 成功 / 1 负发现(未找到 blob) / 2 错误。
- **when_not**: 非 Go 样本时不用(先 die 确认语言)。

### call-site-args

- **用途**: 从反汇编文本提取调用点参数(x64 寄存器/栈槽/x86 push)。
- **用法**:
  ```bash
  python tools/static/call-site-args.py --in <反汇编文本> --abi x64
  ```
- **输入**: 反汇编文本(`--in`) + `--window`/`--abi x64|x86`。
- **输出**: 调用点参数清单(address/target/regs/stack/pushed)。
- **exit code**: 0 成功 / 1 负发现(无调用点) / 2 错误。
- **when_not**: 需要寄存器级数据流精确恢复时不用, 用 ghidra-recon 或模拟执行。

### c-normalize

- **用途**: 反编译 C 规范化: modulo 惯用法 `x-(x/N)*N→x%N` / 死赋值删除; `--heuristics` 开 undefined4/8 类型启发。
- **用法**:
  ```bash
  python tools/static/c_normalize.py --in <反编译C文件> --heuristics
  ```
- **输入**: 反编译 C 文本(`--in` 或 stdin) + `--heuristics` 开关。
- **输出**: 规范化 C + rule_hits/diff stats。
- **exit code**: 0 已变换 / 1 无变换 / 2 错误。
- **when_not**: 语义级反混淆或表达式真值判定不用, 用 opaque-pred。

### opaque-pred

- **用途**: 不透明谓词/MBA 等价判定: 单表达式真值 或 表达式对简化(z3 32-bit 语义)。
- **用法**:
  ```bash
  python tools/static/opaque_pred.py --expr "(x & 1) == 0"
  ```
- **输入**: C 表达式(`--expr "..."`)或表达式对(`--simplify "lhs -> rhs"`); 可选 `--width`。
- **输出**: always_true/always_false/unknown + 简化常量 或 MBA 重写建议。
- **exit code**: 0 已判定(decided) / 1 unknown / 2 错误(z3 缺失带安装指引)。
- **when_not**: 非单表达式真值/MBA 等价判定不用; z3-solver 未装且不允许安装时不用。

### yara-scan

- **用途**: YARA 规则扫描(默认内置 crypto-tables), 输出命中清单。
- **用法**:
  ```bash
  python tools/static/yara-scan.py --binary <样本> --rules tools/static/yara-rules
  ```
- **输入**: 二进制(`--binary`, 必填) + 规则文件/目录(`--rules`, 缺省内置 crypto-tables); 可选 `--max-hits`/`--json`/`--reproduce`。
- **输出**: 命中清单(offset/rule/len/preview)。
- **exit code**: 0 有命中 / 1 无命中 / 2 错误(yara-python 缺失带安装指引)。
- **when_not**: 无规则式扫描需求时不用。

### yara-gen

- **用途**: 从 hex/string 特征模式生成 YARA 规则文本。
- **用法**:
  ```bash
  python tools/static/yara-gen.py --name my_rule --hex AB CD EF --meta family=foo
  ```
- **输入**: 特征模式(`--hex HEX` 或 `--string TEXT`, 至少其一) + `--name`(必填) + `--meta k=v`(可重复); 可选 `--wide`。
- **输出**: YARA 规则文本(stdout)。
- **exit code**: 0 成功 / 2 错误(缺 --name 或特征模式)。
- **when_not**: 不需要从分析发现生成检测规则时不用。
