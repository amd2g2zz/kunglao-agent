# kunglao-agent in-repo toolshelf (tools/ CLIs)

> The repo's own toolshelf, registered on the four discovery faces (#866): the execution
> registry `tools/_INDEX.yaml` (machine contract, consumed by the toolfirst dispatch gate),
> the per-category contract docs `tools/_index-<category>.md`, this teaching page, and the
> `references/_INDEX.md` recall corpus. Registration != mandatory use — selection stays with
> the worker; value ranking is learned (#881), not hardcoded. Contract entries with directly
> copyable invocations live in `tools/_index-<category>.md`; this page is the when-to-reach
> overview. Stems below are the exact CLI file names under `tools/`.

## static triage (tools/static/)

| CLI | What it answers | Reach for when |
|---|---|---|
| `die_probe` | language/compiler/packer/entropy via Detect-It-Easy (5-call merge JSON) | first probe of any new sample before disassembly |
| `pe_analyze` | PE tables: headers/sections/imports/exports/resources/overlay/pdb/tls/signature | structural PE view before any disassembly |
| `overlay_scan` | PE overlay characterization (reloc/entropy/Go evidence/embedded PE) | overlay present or embedded-payload suspicion |
| `disasm_dump` | per-VA capstone disassembly windows | pinned addresses need instruction views |
| `disasm_constant_check` | byte-exact VA-anchored constant assertions | verifying a fact's code-constant claim against the binary |
| `shellcode_scan` | shellcode candidate regions (PEB access/prologues/strings) | blob or PE may carry position-independent code |
| `stack-strings` | `mov [rsp+disp], imm` stack-built string reconstruction | strings missing but stack writes look like character pushes |
| `extract-syscalls` | x64 syscall stub extraction (SSN table) | direct-syscall shellcode / EDR evasion triage |
| `go-buildinfo-carve` | Go buildinfo blob (version/path/deps) | Go binary without symbols |
| `binary-sweep` | byte-pattern sweep: URL/IPv4/domain or custom regex with offsets | quick IOC sweep before deeper static passes |
| `call-site-args` | call-site argument extraction from disassembly | recovering what a function is called with |
| `strings-classify` | entropy/printability/base64-hex classification of strings | triaging which string clusters deserve decoding |
| `yara-scan` | YARA rule scan against the sample | trait confirmation with committed rule assets |
| `yara-gen` | YARA rule generation from extracted traits | turning confirmed byte traits into detection rules |
| `c_normalize` | Ghidra decompiled-C idiom normalization (x-(x/N)*N -> x%N, dead stores) | decompiler output is noisy before pattern reading |
| `opaque_pred` | z3 opaque-predicate truth check + MBA simplification | branch conditions that never vary; MBA expressions |
| `web_gitnexus_demo` | end-to-end #751 semantic-index-layer regression demo (wakaru/webcrack/gitnexus pipeline, `--selfcheck` offline) | verifying the js recovery + graph-query layer works on this host |

## ghidra family (tools/ghidra/)

| CLI | What it answers | Reach for when |
|---|---|---|
| `run_ghidra_postscript` | analyzeHeadless wrapper executing the five Ghidra postScript tools (`ghidra-recon`, `ghidra-decompile-functions`, `ghidra-vtable-struct`, `ghidra-evidence-annotations`, `ghidra-scan-pointer`) | any one-shot Ghidra recon/decompile/vtable/xref job |
| `ghidra_job` | async job protocol over the wrapper: submit / poll / fetch / cancel (+ `job_store.py`, the dir-backed job lib both CLIs share) | Ghidra runs too long to block on — dispatch async, keep polling |
| `ghidra_diff` | binary diff over Ghidra Version Tracking (GhidraBindiff.java -> bindiff.v1 artifact + query subcommands) | two samples/variants need function-level diffing (added/changed/removed) |

## crypto (tools/crypto/)

| CLI | What it answers | Reach for when |
|---|---|---|
| `crypto-tool` | 8-family decode CLI (chacha/xor-add/rolling-xor/lzss/lzma-raw/rsa-unpad/go-byte-transform/va-to-off) | encoded/encrypted layer identified among the supported families |

## android providers (registered capability providers)

| CLI | What it answers | Reach for when |
|---|---|---|
| `apk_mem_gate` | memory-aware jadx dispatch estimator (verdict gates jadx) | before any jadx decompile of a large APK |
| `baksmali_index` | DEX enumeration + xref (1:1 bytecode truth) | smali-level truth needed over decompiled source |
| `dexdc_scanner` | DEX index/taint via the PyO3 wheel (no JVM) | jadx blocked by memory budget or JVM unavailable |

## pipelines + auxiliary (tools/pipelines/, tools/auxiliary/)

| CLI | What it answers | Reach for when |
|---|---|---|
| `build_evidence_index` | registers raw evidence into `evidence/_index.json` (+_INDEX.md) with sha256 + Admiralty reliability | before writing facts that must cite raw evidence (provenance gate P2 rejects unindexed paths) |
| `audit_legacy_proven` | audits PROVEN claims along BLIND sign-off + index-traceability dimensions | hygiene sweep: which PROVEN claims lack verifier/raw-evidence backing |
| `measure_blind_coverage` | BLIND coverage metrics over PROVEN facts | quantifying verifier coverage before delivery |
| `capture_golden` | captures byte-exact golden master fixtures (`tests/fixtures/golden/`) | locking CLI behavior before a refactor (phase-0 freeze flow) |
| `measure_cold_start` | cold-start token baseline over workspace state files | measuring init/context cost of a workspace layout |
| `sanitize` | sample-content prompt-injection sanitizer (zero-width/homoglyph/markers) | before feeding sample-derived text to any LLM worker |
