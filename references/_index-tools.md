# tools 领域索引(文件层)
> 领域:工具链。worker 被派发到工具/反汇编类任务时先读本文件,再按需加载。
| 文件 | 一句话摘要 | 何时读 |
|---|---|---|
| [tools.md](re-library/tools.md) | 核心静态工具:GDB/Radare2/Ghidra(headless+MCP)/Unicorn/Python 字节码/WASM/APK 提取 | 搭建逆向环境或开始静态反汇编前 |
| [tools-dynamic.md](re-library/tools-dynamic.md) | 动态工具:Frida hook/angr/lldb 脚本/x64dbg 自动化/Qiling/EDR | 运行时分析、hook、符号执行、路径探索 |
| [tools-advanced.md](re-library/tools-advanced.md) | 高级工具:VMProtect/Themida 脱壳、BinDiff/Diaphora、D-810/GOOMBA、Triton/Manticore、Rizin | 面对重度加壳/混淆样本或需要二进制 diff/去混淆框架 |
| [tools-crypto.md](re-library/tools-crypto.md) | 加解密/编解码/哈希工具速查(Ciphey/CyberChef/哈希工具/密码求解) | 遇到需要识别、解码或破解的加密/编码/哈希数据 |
