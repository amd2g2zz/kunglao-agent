# #136: Non-PE/ELF Investigation — Go garble / .NET / Rust

## Go garble
- **Current coverage**: `go-symbols` agent runs `unstrip` for Go symbol recovery.
  Garble strips symbol names and type info; unstrip can recover function
  boundaries and some types from runtime tables (pclntab, moduledata).
- **Gap**: Heavily garbled binaries (garble --tiny, garble -seed) may defeat
  unstrip's pclntab parser. No fallback for garbled runtime tables.
- **Assessment**: **Adequate for moderate garbling; gap exists for extreme garble.**
  The kunglao-worker generic fallback (Ghidra decompile + strings) covers
  the residual cases with lower fidelity. No new specialist needed now.

## .NET
- **Current coverage**: No dedicated .NET specialist agent.
- **Available tools**: dnSpy/ilspycmd are standard but NOT installed in the
  analysis VM. Ghidra can decompile .NET to some extent (CIL decoding).
- **Assessment**: **Gap exists for .NET-heavy samples.** Mitigation: add
  `dotnet-decompile` specialist when a .NET sample is encountered. Until then,
  kunglao-worker generic path (DIE detection → Ghidra CIL view) is the fallback.
- **Decision**: No new agent now; document the gap. Create specialist when
  a .NET sample is actually analyzed (YAGNI).

## Rust
- **Current coverage**: No dedicated Rust specialist.
- **Available tools**: Ghidra handles Rust binaries reasonably (calling
  convention, demangling via rustc demangle). Symbol recovery is limited
  due to monomorphization and inlining.
- **Assessment**: **Adequate via generic path.** Rust binaries are
  statically linked and large, but Ghidra + DIE + strings cover the basics.
  No specialist needed — the generic kunglao-worker path is sufficient.

## Conclusion
- Option (a) applies: **existing kunglao-worker generic fallback is sufficient**
  for Go garble (moderate), Rust. .NET is a known gap but YAGNI — create
  a specialist when actually needed.
- No new specialist agents recommended at this time.
- Firmware is explicitly OUT OF SCOPE per user direction.
