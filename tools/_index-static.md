# static 领域索引(工具层)
> 领域:静态识别/特征提取工具。worker 被派发到静态 triage(语言/编译器/加壳识别、字符串、签名)任务时先读本文件,再按需加载。契约字段含义见 [README.md](README.md),机器契约见 [_INDEX.yaml](_INDEX.yaml)。
| 工具 | 契约(一行) | 何时读 / 何时不用 |
|---|---|---|
| `die` | `category: static · capability: static:identify · tier: T1 · cost_tier: probe · input: 样本路径 → output: 语言/编译器/加壳识别 json` | 拿到新样本先做快速识别时读; 已确认加壳族/语言后不用 |
| `die-probe` | `category: static · capability: static:identify · tier: T1 · cost_tier: probe · input: 样本(--binary) + DIE 可执行文件(--die/$KUNGLAO_DIE) → output: DIE 5-call merge json(语言/编译器/加壳/熵/资源); die 缺失 exit 2 + 指引` | 需要 DIE 结构化多面探测(熵/哈希/资源)时读; DIE 未安装时不用 |
| `pe-analyze` | `category: static · capability: static:pe-parse · tier: T1 · cost_tier: cheap · input: 样本(--binary) + 子命令(headers/sections/imports/exports/resources/overlay/pdb/tls/signature) → output: PE 表/数据 json + --reproduce field=value` | 需要 PE 单域解析(导入/导出/资源/PDB/TLS/签名/覆盖区)时读; 需要反汇编时不用(用 disasm-dump) |
| `overlay-scan` | `category: static · capability: static:overlay-scan · tier: T1 · cost_tier: cheap · input: 样本(--binary) + --mode reloc|true|mz|all → output: 覆盖区表征 json(reloc 表/熵/Go 证据/内嵌 PE)` | 怀疑覆盖区藏 reloc 表/Go 载荷/内嵌 PE 时读; 无覆盖区时不用 |
| `disasm-dump` | `category: static · capability: static:disasm · tier: T1 · cost_tier: cheap · input: 样本(--binary) + --rvas/--vas 列表 → output: 每址 capstone 指令清单 json(VA→文件偏移复用 tools/lib_disasm.py)` | 需要指定 RVA/VA 的字节锚定指令清单时读; 函数级语义时不用(用 ghidra-recon) |
| `shellcode-scan` | `category: static · capability: static:shellcode-scan · tier: T1 · cost_tier: cheap · input: blob/PE(--binary) + --scan/--entry/--prologs/--peb/--strings → output: shellcode 候选区域+特征 json` | 怀疑 blob/解密层是 shellcode 时读; 常规 PE 函数分析时不用 |
| `disasm-constant-check` | `category: static · capability: static:disasm-check · tier: T1 · cost_tier: cheap · input: fact/report 清单 + PE 二进制 → output: byte-exact 断言校验 json` | 校验反汇编常量断言(VA 锚点)时读; 无需 byte-exact 校验或没有二进制时不用 |
| `extract-syscalls` | `category: static · capability: static:syscall-extract · tier: T1 · cost_tier: cheap · input: 样本字节(--mode bin)/反汇编文本(--mode text) → output: syscall stub 清单(location/number/name)` | 扫描 x64 syscall stub 编号/名称时读; 非 syscall stub 任务不用 |
| `stack-strings` | `category: static · capability: static:stack-strings · tier: T1 · cost_tier: cheap · input: 样本字节 + --start/--end/--min-len/--dword → output: [rsp+disp] 栈构造字符串清单` | 检测 mov byte/dword [rsp+disp] 栈字符串构造时读; 无该模式时不用 |
| `binary-sweep` | `category: static · capability: static:byte-sweep · tier: T1 · cost_tier: cheap · input: 样本字节 + --kind/--pattern → output: 字节级模式命中(offset/value)` | 直接字节扫描 URL/IP/域名或自定义模式时读; 需节表感知提取时用 die/floss 流程 |
| `strings-classify` | `category: static · capability: static:strings-classify · tier: T1 · cost_tier: cheap · input: 样本字节 + --min-len/--encoding → output: 字符串熵/可打印/可解码分类清单 + inventory` | 字符串熵与 base64/hex 可解码分类时读; 仅需枚举字符串时用 floss |
| `go-buildinfo-carve` | `category: static · capability: static:buildinfo-carve · tier: T1 · cost_tier: cheap · input: 样本字节 + --window/--zero-run → output: Go buildinfo blob 清单(go 版本/path/deps)` | 提取 Go 构建信息(版本/模块/依赖数)时读; 非 Go 样本不用 |
| `call-site-args` | `category: static · capability: static:callsite-args · tier: T1 · cost_tier: cheap · input: 反汇编文本 + --window/--abi → output: 调用点参数清单(regs/stack/pushed)` | 从反汇编文本提取调用点参数时读; 需精确数据流时用 ghidra-recon/模拟执行 |

<!-- 骨架: 每登记一个 static 工具到 _INDEX.yaml,在此追加一行,格式同上。 -->
| `yara-scan` | `category: static · capability: static:yara-scan · tier: T1 · cost_tier: cheap · input: 二进制+规则文件 → output: 命中清单` | 规则式字节扫描(家族/IOC 证据)时; yara-python 缺失不用 |
| `yara-gen` | `category: static · capability: static:yara-gen · tier: T1 · cost_tier: probe · input: 特征模式+meta → output: YARA 规则文本` | 从分析发现生成检测规则时 |
