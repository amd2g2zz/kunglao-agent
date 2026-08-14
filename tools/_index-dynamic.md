# dynamic 领域索引(工具层)

> 领域: VM 动态调试/运行时分析。worker 被派发到动态调试(x64dbg/Frida)类任务时先读本文件, 再按需加载。动态工具一律 VM-only(192.168.20.128)。契约字段含义见 [README.md](README.md), 机器契约见 [_INDEX.yaml](_INDEX.yaml)。
>
> 本域工具由 **MCP + VM 通道**提供, 不在 `_INDEX.yaml` 注册(非本地 .py 脚本): x64dbg 经 `mcp__x64dbg__*`, Frida 经 `mcp__frida__*`(VM `192.168.20.128:1337`)。Frida hook 模板在 `templates/frida/`。

## 工具清单

| 工具 | 用途(一句话) | 何时读 / 何时不用 |
|---|---|---|
| `x64dbg-remote` | VM 侧 x64dbg 远程调试(寄存器/内存/断点/单步) | 需要单步/断点动态验证时读; 纯静态可解的问题不用(VM 成本高) |
| `frida-remote` | VM 侧 Frida 插桩(hook/API 调用捕获/反 hook 检测) | 需要运行时 hook/插桩验证时读; 宿主通道禁止(硬禁令) |

## 契约条目

### x64dbg-remote

- **用途**: 经 MCP 远程连接 VM 上的 x64dbg, 做运行时寄存器/内存/调用栈验证。
- **用法**:
  ```bash
  mcp__x64dbg__connect_remote(host=192.168.20.128)   # 仅 connect_remote; start_session/connect_to_session/connect_to_instance/terminate_session 宿主禁止
  ```
- **输入**: VM 侧已 attach 的进程(连接后按 MCP 工具参数读寄存器/内存/断点)。
- **输出**: 运行时寄存器/内存/调用栈读数(工具返回)。
- **exit code**: N/A(MCP 调用; 失败表现为调用错误/超时, 无 shell exit code)。
- **when_not**: 纯静态可解的问题不用; 宿主通道一律禁止(CLAUDE.md 硬约束)。

### frida-remote

- **用途**: 经 MCP 在 VM 上 spawn/attach 目标进程并注入 Frida hook 脚本。
- **用法**:
  ```bash
  mcp__frida__spawn   # 或 mcp__frida__attach(VM-only: 192.168.20.128:1337)
  ```
- **输入**: VM 目标进程/二进制 + hook 脚本(模板经 `templates/frida/` 生成)。
- **输出**: hook 命中的运行时数据(调用计数/参数/返回值)。
- **exit code**: N/A(MCP 调用; 失败表现为调用错误/超时, 无 shell exit code)。
- **when_not**: 静态分析可解的问题不用; 宿主通道一律禁止(硬禁令 #5)。
