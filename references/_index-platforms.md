# platforms 领域索引(文件层)
> 领域:目标平台与格式。worker 识别出样本平台特征时先读本文件,再按需加载。
| 文件 | 一句话摘要 | 何时读 |
|---|---|---|
| [platforms.md](re-library/platforms.md) | 平台特定逆向总目:macOS/iOS(Mach-O/ObjC/Swift)、嵌入式/IoT 固件、Linux 内核模块、eBPF、Windows 内核驱动、汽车 CAN 总线 | 分析非桌面平台二进制(macOS/iOS 应用、IoT 固件、内核驱动、ECU 软件) |
| [platforms-elf.md](re-library/platforms-elf.md) | ELF 深度参考:头部/节/段/动态链接结构 + Linux/Android 特定反分析对抗 | 逆向 Linux/Android ELF:解析结构、识别 ELF 特定反分析技巧 |
| [platforms-kernel.md](re-library/platforms-kernel.md) | 内核驱动逆向:Windows/Linux 内核驱动、rootkit、C/C++ 二进制模式(WDM/KMDF/minifilter/LKM/eBPF) | 分析内核态代码:.sys 驱动、Linux 内核模块、rootkit、minifilter 文件系统驱动 |
| [platforms-hardware.md](re-library/platforms-hardware.md) | 硬件/高级架构逆向:HD44780 LCD GPIO、RISC-V 扩展/调试、ARM64 利用、MIPS64 密码协处理器、MBR/bootloader | 逆向嵌入式硬件、RISC-V 自定义指令、ARM64 利用、微控制器固件 |
