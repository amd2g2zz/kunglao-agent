# static 领域索引(工具层)
> 领域:静态识别/特征提取工具。worker 被派发到静态 triage(语言/编译器/加壳识别、字符串、签名)任务时先读本文件,再按需加载。契约字段含义见 [README.md](README.md),机器契约见 [_INDEX.yaml](_INDEX.yaml)。
| 工具 | 契约(一行) | 何时读 / 何时不用 |
|---|---|---|
| `die` | `category: static · capability: static:identify · tier: T1 · cost_tier: probe · input: 样本路径 → output: 语言/编译器/加壳识别 json` | 拿到新样本先做快速识别时读; 已确认加壳族/语言后不用 |
| `disasm-constant-check` | `category: static · capability: static:disasm-check · tier: T1 · cost_tier: cheap · input: fact/report 清单 + PE 二进制 → output: byte-exact 断言校验 json` | 校验反汇编常量断言(VA 锚点)时读; 无需 byte-exact 校验或没有二进制时不用 |
| `extract-syscalls` | `category: static · capability: static:syscall-extract · tier: T1 · cost_tier: cheap · input: 样本字节(--mode bin)/反汇编文本(--mode text) → output: syscall stub 清单(location/number/name)` | 扫描 x64 syscall stub 编号/名称时读; 非 syscall stub 任务不用 |
| `stack-strings` | `category: static · capability: static:stack-strings · tier: T1 · cost_tier: cheap · input: 样本字节 + --start/--end/--min-len/--dword → output: [rsp+disp] 栈构造字符串清单` | 检测 mov byte/dword [rsp+disp] 栈字符串构造时读; 无该模式时不用 |
| `binary-sweep` | `category: static · capability: static:byte-sweep · tier: T1 · cost_tier: cheap · input: 样本字节 + --kind/--pattern → output: 字节级模式命中(offset/value)` | 直接字节扫描 URL/IP/域名或自定义模式时读; 需节表感知提取时用 die/floss 流程 |
| `strings-classify` | `category: static · capability: static:strings-classify · tier: T1 · cost_tier: cheap · input: 样本字节 + --min-len/--encoding → output: 字符串熵/可打印/可解码分类清单 + inventory` | 字符串熵与 base64/hex 可解码分类时读; 仅需枚举字符串时用 floss |
| `go-buildinfo-carve` | `category: static · capability: static:buildinfo-carve · tier: T1 · cost_tier: cheap · input: 样本字节 + --window/--zero-run → output: Go buildinfo blob 清单(go 版本/path/deps)` | 提取 Go 构建信息(版本/模块/依赖数)时读; 非 Go 样本不用 |
| `call-site-args` | `category: static · capability: static:callsite-args · tier: T1 · cost_tier: cheap · input: 反汇编文本 + --window/--abi → output: 调用点参数清单(regs/stack/pushed)` | 从反汇编文本提取调用点参数时读; 需精确数据流时用 ghidra-recon/模拟执行 |

<!-- 骨架: 每登记一个 static 工具到 _INDEX.yaml,在此追加一行,格式同上。 -->
