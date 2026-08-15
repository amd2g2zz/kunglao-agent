# tools domain index (file level)
> Domain: toolchain. When a worker is dispatched to tooling/disassembly tasks, read this file first, then load on demand.
| File | One-line summary | When to read |
|---|---|---|
| [tools.md](re-library/tools.md) | Core static tools: GDB/Radare2/Ghidra (headless+MCP)/Unicorn/Python bytecode/WASM/APK extraction | Before setting up an RE environment or starting static disassembly |
| [tools-dynamic.md](re-library/tools-dynamic.md) | Dynamic tools: Frida hooking/angr/lldb scripts/x64dbg automation/Qiling/EDR | Runtime analysis, hooking, symbolic execution, path exploration |
| [tools-advanced.md](re-library/tools-advanced.md) | Advanced tools: VMProtect/Themida unpacking, BinDiff/Diaphora, D-810/GOOMBA, Triton/Manticore, Rizin | Facing heavily packed/obfuscated samples or needing binary diffing/deobfuscation frameworks |
| [tools-crypto.md](re-library/tools-crypto.md) | Crypto/encoding/hashing tool quick reference (Ciphey/CyberChef/hash tools/password solvers) | Encrypted/encoded/hashed data needs identification, decoding, or cracking |
