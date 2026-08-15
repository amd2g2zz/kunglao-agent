# platforms domain index (file level)
> Domain: target platforms and formats. When a worker identifies platform traits in a sample, read this file first, then load on demand.
| File | One-line summary | When to read |
|---|---|---|
| [platforms.md](re-library/platforms.md) | Master catalog of platform-specific RE: macOS/iOS (Mach-O/ObjC/Swift), embedded/IoT firmware, Linux kernel modules, eBPF, Windows kernel drivers, automotive CAN bus | Analyzing non-desktop-platform binaries (macOS/iOS apps, IoT firmware, kernel drivers, ECU software) |
| [platforms-elf.md](re-library/platforms-elf.md) | Deep ELF reference: header/section/segment/dynamic-linking structure + Linux/Android-specific anti-analysis adversary techniques | Reversing Linux/Android ELF: parsing structures, recognizing ELF-specific anti-analysis tricks |
| [platforms-kernel.md](re-library/platforms-kernel.md) | Kernel driver RE: Windows/Linux kernel drivers, rootkits, C/C++ binary patterns (WDM/KMDF/minifilter/LKM/eBPF) | Analyzing kernel-mode code: .sys drivers, Linux kernel modules, rootkits, minifilter file-system drivers |
| [platforms-hardware.md](re-library/platforms-hardware.md) | Hardware/advanced-architecture RE: HD44780 LCD GPIO, RISC-V extensions/debug, ARM64 exploitation, MIPS64 crypto coprocessor, MBR/bootloader | Reversing embedded hardware, RISC-V custom instructions, ARM64 exploitation, microcontroller firmware |
