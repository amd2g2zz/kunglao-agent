# languages domain index (file level)
> Domain: target languages. When a worker identifies language traits in a sample, read this file first, then load on demand.
| File | One-line summary | When to read |
|---|---|---|
| [languages.md](re-library/languages.md) | Scripting/niche-language RE: Python bytecode/opcodes, Pyarmor unpacking, DOS stub, HarmonyOS HAP, Brainfuck, UEFI, transpiled code | Sample is a non-standard language target (Python bytecode, esolang, UEFI firmware, HarmonyOS) |
| [languages-compiled.md](re-library/languages-compiled.md) | Non-C compiled language quick reference: Go/Rust/Swift/Kotlin-JVM/D/Haskell/C++ (vtable/RTTI/stdlib patterns) | Facing a non-C compiled binary needing language-specific decompiler heuristics or symbol-recovery tricks |
| [languages-go.md](re-library/languages-go.md) | Go binary RE end to end: trait identification, stripped-symbol recovery, memory layout, dedicated toolchain | Statically linked Go samples: massive symbol tables, goroutine structures, stripped metadata |
| [languages-platforms.md](re-library/languages-platforms.md) | Platform/framework-specific RE: Android JNI/Dex, Electron, Node.js, Verilog, Intel SGX, certificate-pinning bypass, etc. | Sample is bound to a specific platform or framework (Android app, Electron bundle, SGX enclave, FPGA bitstream) |
