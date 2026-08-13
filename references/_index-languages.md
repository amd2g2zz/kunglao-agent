# languages 领域索引(文件层)
> 领域:目标语言。worker 识别出样本语言特征时先读本文件,再按需加载。
| 文件 | 一句话摘要 | 何时读 |
|---|---|---|
| [languages.md](re-library/languages.md) | 脚本/小众语言逆向:Python 字节码/opcodes、Pyarmor 脱壳、DOS stub、HarmonyOS HAP、Brainfuck、UEFI、转译 | 样本为非标准语言目标(Python 字节码、esolang、UEFI 固件、HarmonyOS) |
| [languages-compiled.md](re-library/languages-compiled.md) | 非 C 编译型语言速查:Go/Rust/Swift/Kotlin-JVM/D/Haskell/C++(vtable/RTTI/stdlib 模式) | 遇到非 C 编译型二进制,需要语言特定反编译启发式或符号恢复技巧 |
| [languages-go.md](re-library/languages-go.md) | Go 二进制逆向全流程:特征识别、strip 符号恢复、内存布局、专用工具链 | 静态链接 Go 样本:海量符号表、goroutine 结构、strip 元数据 |
| [languages-platforms.md](re-library/languages-platforms.md) | 平台/框架特定逆向:Android JNI/Dex、Electron、Node.js、Verilog、Intel SGX、证书固定绕过等 | 样本绑定特定平台或框架(Android 应用、Electron 包、SGX 飞地、FPGA 比特流) |
