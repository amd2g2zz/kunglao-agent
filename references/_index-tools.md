# tools domain index (file level)
> GENERATED FILE — regenerate with `python scripts/reference_index_build.py`.
> Row summaries are the card frontmatter descriptions, byte-for-byte.
| File | Summary |
|---|---|
| [kunglao-toolshelf.md](re-library/tools/shelf/kunglao-toolshelf.md) | The repo's own toolshelf of `tools/` CLIs (#866 four-face registration): static triage (die_probe, pe_analyze, disasm_dump, overlay_scan, shellcode_scan, stack-strings, extract-syscalls, go-buildinfo-carve, binary-sweep, call-site-args, c_normalize, opaque_pred, disasm_constant_check, yara-scan, yara-gen), ghidra family (run_ghidra_postscript, ghidra_job async + ghidra_diff), crypto-tool, android providers (apk_mem_gate, baksmali_index), pipelines/aux (build_evidence_index, audit_legacy_proven, measure_blind_coverage, capture_golden, measure_cold_start, sanitize). When choosing an in-repo CLI for a RE task or checking what the shelf can already do — pair with the per-tool contract entries in `tools/_index-<category>.md`. |
| [tools-advanced.md](re-library/tools/static/tools-advanced.md) | Advanced RE tooling: unpackers, diffing, symbolic exec. When facing heavily packed/obfuscated binaries. |
| [tools-crypto.md](re-library/tools/crypto/tools-crypto.md) | Encryption/encoding/hashing tool quick-reference. When needing to identify/decode/crack encrypted data. |
| [tools-dynamic.md](re-library/tools/dynamic/tools-dynamic.md) | Dynamic analysis tooling (Frida, angr, lldb, x64dbg, Qiling). When performing runtime/dynamic analysis or function hooking. |
| [tools.md](re-library/tools/static/tools.md) | Core static RE tools (GDB, Radare2, Ghidra, Unicorn). When setting up a reversing workspace. |
