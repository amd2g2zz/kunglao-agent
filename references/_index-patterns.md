# patterns 领域索引(文件层)
> 领域:分析模式(通用逆向技巧)。worker 遇到模式识别类任务时先读本文件,再按需加载。
| 文件 | 一句话摘要 | 何时读 |
|---|---|---|
| [patterns.md](re-library/patterns.md) | 通用逆向模式总目:自定义 VM、反调试绕过、自修改代码、XOR、LLVM CFF、S-box/密钥流等 | 分析混淆二进制时需要识别模式归属与入手方式 |
| [patterns-simulation.md](re-library/patterns-simulation.md) | 模拟执行与加载器:自定义虚拟机/仿真器逆向、shellcode 与多级加载器、内存中解密、运行时密钥提取 | 样本含自定义 VM/仿真器、内存加载 shellcode、自解密 loader、无导入 API 解析 |
| [patterns-decode.md](re-library/patterns-decode.md) | 解码与去混淆:多层自解密、.rodata XOR 字符串去混淆、嵌入数据提取、ROPfuscation、格基/GF(2^8) 求解 | 样本为多层自解密/混淆字符串/授权校验,或需约束求解恢复目标数据 |
| [patterns-debugging.md](re-library/patterns-debugging.md) | 动态调试与分析:Z3 约束求解、断点/跟踪/侧信道、VM 顺序密钥链、架构特定固件、BPF/网络过滤分析 | 样本隐藏校验逻辑(析构/死分支/时间锁定)、需动态跟踪或符号化求解 |
