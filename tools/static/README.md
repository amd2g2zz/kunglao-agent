# tools/static — static analysis tool home

This directory is the `static` category's tool home: purely local static-analysis CLIs — PE parsing, string and entropy extraction, syscall/stack-string/overlay scanning, disassembly comparison and listing validation, and more. 16 tools are currently registered (see `tools/_INDEX.yaml`).

## Relation to the index docs

A worker reads `tools/_index-static.md` first (the 6-segment contract entries for the 16 tools: 用途/用法/输入/输出/exit code/when_not, with directly copyable usage); this README only explains the in-home file division and absorption history. The machine contract is `tools/_INDEX.yaml`.

## Absorbed tools (issue #278 PR-1b, 6 zero-dependency CLIs)

| Tool | Source script | One-line contract |
|---|---|---|
| `extract-syscalls.py` | `2026-06-10/scripts/extract_syscalls.py` | x64 syscall stub extraction (`mov eax, imm; syscall` / `mov r10, rcx` backtrack + NT name table) |
| `stack-strings.py` | `2026-06-10/scripts/check_stack_strings.py` | `mov byte/dword [rsp+disp], imm` stack-built string reconstruction |
| `binary-sweep.py` | `2026-07-01/scripts/binary_sweep.py` | URL/IPv4/domain/custom byte-regex scanning, with file offsets |
| `strings-classify.py` | `2026-06-10/scripts/analyze_decrypted.py` + `2026-07-01/scripts/floss_filter.py` | string entropy/printability/decodability (base64/hex) classification |
| `go-buildinfo-carve.py` | `2026-06-10/evidence/pe-analysis/verify_go_buildinfo.py` + `2026-06-10/scripts/gap_determinative.py` | Go buildinfo location and parsing (version/path/deps) |
| `call-site-args.py` | `2026-06-10/scripts/analysis/build_xpsplog_payload_evidence.py` + `2026-06-10/scripts/analysis/qiling_npwzwmc64_realargs_native_probe.py` | call-site argument extraction from disassembly text (x64 registers/stack slots/x86 pushes) |

`common.py` is the shared CLI plumbing (#277 contract: 0/1/2 three-state exit codes, `--json`, `--reproduce` field=value, errors with guidance); it is not a tool and is not registered in the index.

## Absorbed tools (issue #278 PR-1c)

| File | Tool | Responsibility |
|---|---|---|
| `pe_analyze.py` | `pe-analyze` | PE trunk parsing: headers/sections/imports/exports/resources/overlay/pdb/tls/signature subcommands |
| `overlay_scan.py` | `overlay-scan` | overlay 3-in-1: `--mode reloc\|true\|mz` (reloc table / true-overlay / embedded MZ PE) |
| `disasm_dump.py` | `disasm-dump` | capstone instruction listing for given RVAs/VAs (reuses the VA→offset core of `tools/_lib/lib_disasm.py`) |
| `shellcode_scan.py` | `shellcode-scan` | shellcode blob detection: entry disassembly/code-region scanning/prologues/PEB access/strings |
| `die_probe.py` | `die-probe` | DIE 5-call merge probe wrapper (missing die → exit 2 + install guidance) |

Other registered tools: `yara-scan.py` + `yara-gen.py` (issue #313, absorbing the findcrypt-yara rule assets into `yara-rules/`), `c_normalize.py` + `opaque_pred.py` (issue #306, decompiled-C post-processing), `disasm_constant_check.py` (issue #284; homed in this directory from the tools/ root layer since #340).

## Shared module (#340 merge)

`common.py` is the static category's **single** shared module (#340 structure rule: one shared module per category). #340 merged the original two modules into one and kept the whole public surface:

- CLI plumbing (original `common.py`): `error`/`add_common_flags`/`read_bytes`/`read_text`/`parse_int`/`sha256`/`parse_line`/`report`/`negative` + `EXIT_*`/`L1_FIELD_RE` (#277 contract).
- byte-scan helpers (original `_common.py`, #278 PR-1c): `EXE_SIGNATURES`/`X64_PROLOG_PATTERNS`/`PEB_ACCESS_PATTERNS`/`find_all`/`signature_hits`/`ascii_strings`/`x64_prolog_offsets`/`byte_entropy`/`uniform_variance`/`scan_valid_pclntab`.

`tools/_lib/lib_disasm.py` (the cross-category shared-library single point) provides the PE/capstone VA→offset core and does not live in this directory.

lzma-raw is no longer absorbed separately: the `lzma-raw` subcommand of `tools/crypto/crypto-tool.py` (`algorithms.lzma_raw_decompress`, dict_size/lc/lp/pb/size fully parameterized) already covers the same capability, avoiding duplication.

## Contract essentials (#277)

- All fully parameterized, read-only idempotent, three-state exit codes: 0 success / 1 negative finding (ran, no result) / 2 error (bad arguments/unreadable input, with guidance).
- `--json` default output is a single JSON object + `--reproduce` field=value lines (kunglao L1 mechanical gate).
- Per-tool usage/exit-code specifics defer to the contract entries in `tools/_index-static.md`.
