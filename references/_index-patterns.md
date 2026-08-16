# patterns domain index (file level)
> Domain: analysis patterns (general RE techniques). When a worker hits a pattern-recognition task, read this file first, then load on demand.
| File | One-line summary | When to read |
|---|---|---|
| [patterns.md](re-library/patterns.md) | Master catalog of general RE patterns: custom VMs, anti-debug bypasses, self-modifying code, XOR, LLVM CFF, S-box/keystream, etc. | Analyzing an obfuscated binary and needing to identify the pattern family and the entry point |
| [patterns-simulation.md](re-library/patterns-simulation.md) | Simulated execution and loaders: custom VM/emulator RE, shellcode and multi-stage loaders, in-memory decryption, runtime key extraction | Sample contains a custom VM/emulator, in-memory shellcode loading, a self-decrypting loader, or import-less API resolution |
| [patterns-decode.md](re-library/patterns-decode.md) | Decoding and deobfuscation: multi-layer self-decryption, .rodata XOR string deobfuscation, embedded data extraction, ROPfuscation, lattice/GF(2^8) solving | Sample is multi-layer self-decrypting/obfuscated strings/license checks, or constraint solving is needed to recover target data |
| [patterns-debugging.md](re-library/patterns-debugging.md) | Dynamic debugging and analysis: Z3 constraint solving, breakpoints/tracing/side channels, VM sequential key chains, architecture-specific firmware, BPF/network filter analysis | Sample hides validation logic (destructors/dead branches/time locks), or needs dynamic tracing or symbolic solving |
