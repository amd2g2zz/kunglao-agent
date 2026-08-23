# static domain index (tool layer)

> Domain: static identification / trait-extraction tools. When a worker is dispatched to static triage (language/compiler/packer identification, strings, signatures, disassembly validation) tasks, read this file first, then load on demand. Contract field meanings are in [README.md](README.md); the machine contract is [_INDEX.yaml](_INDEX.yaml).

## Tool catalog

| Tool | Purpose (one-liner) | When to read / when not |
|---|---|---|
| `die-probe` | DIE 5-call merge probe (language/compiler/packer/entropy/resources) | Read when structured multi-facet DIE probing is needed; not when DIE is not installed |
| `pe-analyze` | PE table parsing (headers/sections/imports/exports/resources/overlay/pdb/tls/signature) | Read when single-domain PE parsing is needed; for disassembly use disasm-dump |
| `overlay-scan` | Overlay 3-in-1 characterization (reloc/true/mz) | Read when the overlay is suspected of hiding a reloc table/embedded PE; not when there is no overlay |
| `disasm-dump` | capstone instruction listing for given RVAs/VAs | Read when a byte-anchored instruction listing is needed; for function-level semantics use ghidra-recon |
| `shellcode-scan` | shellcode/blob detection (entry disassembly/prologue/PEB/strings) | Read when a blob/decryption layer is suspected to be shellcode; not for routine PE function analysis |
| `disasm-constant-check` | byte-exact disassembly constant validation (VA anchors) | Read when validating disassembly constant assertions; not without a binary sample |
| `extract-syscalls` | x64 syscall stub extraction (numbers/names) | Read when scanning syscall stub numbers/names; not for non-syscall-stub tasks |
| `stack-strings` | `[rsp+disp]` stack-built string reconstruction | Read when detecting stack-string construction patterns; not without such patterns |
| `binary-sweep` | Byte-level URL/IP/domain/custom-regex scanning | Read for direct byte-pattern scanning; for section-aware extraction use the die/floss flow |
| `strings-classify` | String entropy/printability/decodability classification + inventory | Read when classifying string entropy and base64/hex decodability; for plain string enumeration use floss |
| `go-buildinfo-carve` | Go buildinfo blob location and parsing | Read when extracting Go build info; not for non-Go samples (confirm language with die first) |
| `rust-dep-strings` | Rust crate dependency-string carving (registry paths / standalone name-version) | Read when extracting Rust crate deps; not for non-Rust samples (confirm language with die first) |
| `call-site-args` | Call-site argument extraction from disassembly text (x64/x86) | Read when extracting call-site arguments from disassembly text; for precise dataflow use ghidra-recon/emulated execution |
| `c-normalize` | Decompiled-C normalization (modulo idioms/dead stores) | Read to normalize before a worker reads Ghidra decompiled C; for semantic deobfuscation use opaque-pred |
| `opaque-pred` | Opaque predicate/MBA equivalence decision (z3) | Read when statically resolving opaque predicates/proving MBA equivalences; not when z3 is absent or the task is not expression-level |
| `yara-scan` | YARA rule scanning (built-in crypto-tables) | Read for rule-based byte scanning (family/IOC evidence); not when yara-python is missing |
| `yara-gen` | YARA rule text generation from analysis findings | Read when generating detection rules from hex/string traits; not without a rule-generation need |

## Contract entries

### die-probe

- **Purpose**: Run the DIE 5-call merge probe against a PE sample; emit structured identification of language/compiler/packer/entropy/resources.
- **Usage**:
  ```bash
  python tools/static/die_probe.py --binary <sample-PE> --die <path-to-diec.exe>
  ```
- **Inputs**: Sample PE (`--binary`, required) + DIE executable (`--die` or `$KUNGLAO_DIE` or diec on PATH).
- **Outputs**: DIE 5-call merge JSON (`--json` default; `--reproduce` emits field=value lines).
- **exit code**: 0 success / 1 all 5 DIE calls failed / 2 error (missing die with install guidance / bad arguments).
- **when_not**: Not when DIE is not installed and installing is not allowed.

### pe-analyze

- **Purpose**: Single-domain PE parsing: headers/sections/imports/exports/resources/overlay/pdb/tls/signature subcommands.
- **Usage**:
  ```bash
  python tools/static/pe_analyze.py --binary <sample-PE> imports
  ```
- **Inputs**: Sample PE (`--binary`, required) + subcommand (headers/sections/imports/exports/resources/overlay/pdb/tls/signature, default all).
- **Outputs**: The requested PE table/data JSON + `--reproduce` field=value lines.
- **exit code**: 0 success / 1 negative finding (subcommand has no content) / 2 error.
- **when_not**: Not for instruction-level disassembly or function-level views — use disasm-dump / ghidra-recon.

### overlay-scan

- **Purpose**: PE overlay 3-in-1 characterization: reloc table / true-overlay / embedded MZ PE.
- **Usage**:
  ```bash
  python tools/static/overlay_scan.py --binary <sample-PE> --mode all
  ```
- **Inputs**: Sample PE (`--binary`, required) + `--mode reloc|true|mz|all`.
- **Outputs**: Overlay characterization JSON (reloc table/entropy/Go evidence/embedded-PE hits).
- **exit code**: 0 positive finding / 1 negative finding (no overlay evidence) / 2 error.
- **when_not**: Not when the PE has no overlay or there is no embedded-payload suspicion.

### disasm-dump

- **Purpose**: capstone instruction listing for given RVAs/VAs (VA→file-offset reuse of tools/_lib/lib_disasm.py).
- **Usage**:
  ```bash
  python tools/static/disasm_dump.py --binary <sample-PE> --rvas 0x1000,0x2000
  ```
- **Inputs**: Sample PE (`--binary`, required) + `--rvas`/`--vas` address list; optional `--prologs`/`--strings`/`--length`.
- **Outputs**: Per-address capstone instruction listing JSON.
- **exit code**: 0 all succeeded / 1 some addresses failed / 2 error.
- **when_not**: Not for function-level semantics/decompilation — use ghidra-recon / ghidra-decompile-functions.

### shellcode-scan

- **Purpose**: shellcode/blob detection: entry disassembly/code-region scanning/prologues/PEB access/strings.
- **Usage**:
  ```bash
  python tools/static/shellcode_scan.py --binary <blob-or-PE> --scan --entry 0x0
  ```
- **Inputs**: Binary blob/PE (`--binary`, required) + `--scan`/`--entry`/`--prologs`/`--peb`/`--strings`.
- **Outputs**: Shellcode candidate regions + trait JSON (PEB access/prologues/strings/entry disassembly).
- **exit code**: 0 hits / 1 no hits / 2 error.
- **when_not**: Not for non-shellcode/blob detection tasks.

### disasm-constant-check

- **Purpose**: byte-exact assertion validation of fact/report code listings (VA anchors).
- **Usage**:
  ```bash
  python tools/static/disasm_constant_check.py --binary <sample-PE> --fact <facts/F-NN.md>
  ```
- **Inputs**: fact/report code listing (`--fact` or `--report`+`--reference`) + PE binary (`--binary`, required).
- **Outputs**: byte-exact assertion validation JSON (ok/mismatches/errors/skipped).
- **exit code**: 0 all assertions ok / 1 mismatch present / 2 error.
- **when_not**: Not when VA-anchored constant validation is unnecessary or there is no binary sample.

### extract-syscalls

- **Purpose**: x64 syscall stub extraction (`mov eax, imm; syscall` / `mov r10, rcx` backtrack + NT name table).
- **Usage**:
  ```bash
  python tools/static/extract-syscalls.py --in <sample> --mode bin
  ```
- **Inputs**: Sample bytes (`--in` + `--mode bin`) or disassembly text (`--mode text`); optional `--no-names`/`--max-back`.
- **Outputs**: syscall stub listing (location/number/name) + `--reproduce` field=value lines.
- **exit code**: 0 success / 1 negative finding (no stubs) / 2 error.
- **when_not**: Not for non-x64-syscall-stub scanning tasks.

### stack-strings

- **Purpose**: `mov byte/dword [rsp+disp], imm` stack-built string reconstruction.
- **Usage**:
  ```bash
  python tools/static/stack-strings.py --in <sample> --start 0x0 --end 0x1000
  ```
- **Inputs**: Sample bytes (`--in`) + `--start`/`--end` range; optional `--min-len`/`--dword`.
- **Outputs**: `[rsp+disp]` stack-built string listing (slot/value/writes).
- **exit code**: 0 success / 1 negative finding (no hits) / 2 error (invalid range etc.).
- **when_not**: Not without mov byte/dword [rsp+disp] stack-write patterns.

### binary-sweep

- **Purpose**: Byte-level pattern scanning: URL/IPv4/domain or a custom byte regex, with file offsets.
- **Usage**:
  ```bash
  python tools/static/binary-sweep.py --in <sample> --kind all
  ```
- **Inputs**: Sample bytes (`--in`) + `--kind url|ipv4|domain|all` or `--pattern <regex>`; optional `--max`.
- **Outputs**: Byte-level pattern hit listing (kind/offset/value).
- **exit code**: 0 success / 1 negative finding (no hits) / 2 error (invalid pattern etc.).
- **when_not**: Not for PE section-aware structured string extraction — use the die/floss flow.

### strings-classify

- **Purpose**: String entropy/printability/decodability (base64/hex) classification + inventory statistics.
- **Usage**:
  ```bash
  python tools/static/strings-classify.py --in <sample> --encoding both
  ```
- **Inputs**: Sample bytes (`--in`) + `--min-len`/`--encoding ascii|utf16le|both`.
- **Outputs**: String classification listing (entropy/printable_ratio/base64/hex) + inventory statistics.
- **exit code**: 0 success / 1 negative finding (no strings) / 2 error.
- **when_not**: Not when floss already extracted everything and no entropy/decodability classification is needed.

### go-buildinfo-carve

- **Purpose**: Go buildinfo blob location and parsing (go version/path/mod count/dep count/size).
- **Usage**:
  ```bash
  python tools/static/go-buildinfo-carve.py --in <sample> --window 50000
  ```
- **Inputs**: Sample bytes (`--in`) + `--window`/`--zero-run` arguments.
- **Outputs**: Go buildinfo blob listing (offset/go_version/path/mod_count/dep_count/size).
- **exit code**: 0 success / 1 negative finding (no blob found) / 2 error.
- **when_not**: Not for non-Go samples (confirm the language with die first).

### rust-dep-strings

- **Purpose**: Rust crate dependency-string carving (dual channel: cargo registry paths with 16-hex registry ids + standalone crate-name-version strings).
- **Usage**:
  ```bash
  python tools/static/rust-dep-strings.py --in <sample> --channels registry,crate
  ```
- **Inputs**: Sample bytes (`--in`) + `--channels` (comma-separated subset of `registry,crate`; default both).
- **Outputs**: Crate name+version listing with source channel per hit, plus registry ids and `registry+` source URLs (`--json` object / `--reproduce` field=value).
- **exit code**: 0 success / 1 negative finding (no crate, registry id, or source found) / 2 error.
- **when_not**: Not for non-Rust samples (confirm the language with die first); the standalone-crate channel alone is weaker evidence than the registry channel.

### call-site-args

- **Purpose**: Extract call-site arguments from disassembly text (x64 registers/stack slots/x86 pushes).
- **Usage**:
  ```bash
  python tools/static/call-site-args.py --in <disasm-text> --abi x64
  ```
- **Inputs**: Disassembly text (`--in`) + `--window`/`--abi x64|x86`.
- **Outputs**: Call-site argument listing (address/target/regs/stack/pushed).
- **exit code**: 0 success / 1 negative finding (no call sites) / 2 error.
- **when_not**: Not for register-level dataflow-precise recovery — use ghidra-recon or emulated execution.

### c-normalize

- **Purpose**: Decompiled-C normalization: modulo idiom `x-(x/N)*N→x%N` / dead-store elimination; `--heuristics` enables undefined4/8 type heuristics.
- **Usage**:
  ```bash
  python tools/static/c_normalize.py --in <decompiled-C-file> --heuristics
  ```
- **Inputs**: Decompiled C text (`--in` or stdin) + `--heuristics` switch.
- **Outputs**: Normalized C + rule_hits/diff stats.
- **exit code**: 0 transformed / 1 no transformation / 2 error.
- **when_not**: Not for semantic deobfuscation or expression truth-value decisions — use opaque-pred.

### opaque-pred

- **Purpose**: Opaque predicate/MBA equivalence decision: single-expression truth value or expression-pair simplification (z3 32-bit semantics).
- **Usage**:
  ```bash
  python tools/static/opaque_pred.py --expr "(x & 1) == 0"
  ```
- **Inputs**: A C expression (`--expr "..."`) or an expression pair (`--simplify "lhs -> rhs"`); optional `--width`.
- **Outputs**: always_true/always_false/unknown + simplified constant or MBA rewrite suggestion.
- **exit code**: 0 decided / 1 unknown / 2 error (missing z3 with install guidance).
- **when_not**: Not for non-single-expression truth-value/MBA-equivalence decisions; not when z3-solver is not installed and installing is not allowed.

### yara-scan

- **Purpose**: YARA rule scanning (built-in crypto-tables by default); emits a hit listing.
- **Usage**:
  ```bash
  python tools/static/yara-scan.py --binary <sample> --rules tools/static/yara-rules
  ```
- **Inputs**: Binary (`--binary`, required) + rules file/directory (`--rules`, default built-in crypto-tables); optional `--max-hits`/`--json`/`--reproduce`.
- **Outputs**: Hit listing (offset/rule/len/preview).
- **exit code**: 0 hits / 1 no hits / 2 error (missing yara-python with install guidance).
- **when_not**: Not when there is no rule-based scanning need.

### yara-gen

- **Purpose**: Generate YARA rule text from hex/string trait patterns.
- **Usage**:
  ```bash
  python tools/static/yara-gen.py --name my_rule --hex AB CD EF --meta family=foo
  ```
- **Inputs**: Trait patterns (`--hex HEX` or `--string TEXT`, at least one) + `--name` (required) + repeatable `--meta k=v`; optional `--wide`.
- **Outputs**: YARA rule text (stdout).
- **exit code**: 0 success / 2 error (missing --name or trait pattern).
- **when_not**: Not when detection rules do not need to be generated from analysis findings.
