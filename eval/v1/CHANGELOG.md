# eval-v1 changelog

## eval-v1 (#299 smoke tier — initial)

- Corpus layout created: `eval/v1/tasks/smoke/` with three constructed
  targets (ground truth by construction, seeded variants of known
  mechanism families):
  - `go-arx-v1` — SHA-1-family KDF, mutated K0/golden/rot-base constants;
    constant-hit (static) + pair-match (reproduction, >= 12 of 16) oracles.
  - `js-sign-v1` — obfuscated-style signer bundle, two load-bearing
    constants + two decoys; constant-hit + replay-roundtrip over published
    and checker-minted probes.
  - `py-derive-v1` — 64-bit pure-algo derivation; replay-roundtrip over
    published and checker-minted probes (anti-digest-table).
- Task-unit schema: `schemas/eval-task-v1.json` (+ validator in
  `scripts/eval_dataset.py`).
- Mechanical checker: `scripts/eval_checker.py` (METRIC emission,
  arithmetic verdict, evidence archive, structured failure signals,
  toolchain-skip contract).
- Smoke-tier runner: `scripts/eval_smoke_runner.py` (#295-shaped results
  rows; `--candidate-for` = the #236 control-arm execution surface;
  `--baselines` = 1/k guessing floor).
- Held-out path contract: `EVAL_CORPUS_PREFIXES` +
  `filter_distiller_sources` — eval tasks never enter the #298
  distillation corpus.

## Rules for future versions

- A version used for a capability claim is never mutated in place: churn
  mints `eval-v2/` + a new changelog section (seeds may be re-drawn;
  variants must stay divergent).
- Every task keeps its `seed` so any unit can be re-minted
  byte-identically.

## eval-v1.1 (#332 release tier — the native ladder)

Additive bump: the smoke tier (eval-v1) is unchanged and still valid; new
units mint `eval_version: eval-v1.1`, `tier: release`, under
`eval/v1/tasks/release/`. Twelve units across four families, one seed per
family (33201-33204), every constant synthetic and seeded:

- `arm-native-kdf` (L0/L1/L2) — real Android arm64 .so via the NDK
  (`aarch64-linux-android29-clang -shared -Wl,--build-id=none`, stripped
  from L1); exported `kdf_derive` over the mod-SHA counter KDF.
- `win-pe-kdf` (L0/L1/L2/L2p) — real Windows PE via Go (GOOS=windows
  GOARCH=amd64 CGO_ENABLED=0, `-ldflags "-s -w -buildid="`). L2p = genuine
  UPX packing: PE/UPX builds are timestamp-nondeterministic, so mint
  verifies by UNPACKING, never byte-identity. The exe itself is not
  committed: a Go PE exceeds the 200KB committed-artifact budget even
  packed (empty-main floor ~427KB packed), so mint records full build
  evidence (magic, size, sha256, constant/anti-debug scans) and commits
  the real source.
- `smc-x86` (L0/L1/L2) — x86_64 freestanding ELF (clang 22
  `--target=x86_64-linux-gnu -nostdlib -static -fuse-ld=lld`). Genuine
  SMC: the payload's `.text` is XOR-encrypted in the image by the
  generator; the stub decrypts in place gated on anti-debug.
- `mod-crypto-native` (L1/L2) — the mod-crypto core as a standalone
  arm64 .so. No L0: stock crypto is exactly the anti-standard regression.

Binding additions baked into every family:

- **mod-crypto core** (`scripts/eval_crypto.py`): seed-derived mutation
  generator — mod-AES-128 (S-box = FIPS-197 S-box composed with a seeded
  permutation, bijective; mutated Rcon) and mod-SHA-256 (mutated H/K).
  Seed 0 = identity (FIPS-197/FIPS-180 vectors pin the implementation);
  every nonzero seed diverges from stock on the first block, so a
  hashlib/stock-AES candidate fails by construction (the anti-standard
  cheat regression). The KDFs are built ON mod-SHA; the SMC payload IS a
  mod-crypto implementation.
- **anti-debug on every native sample**: TracerPid parse (seed-masked
  needle at source level), ptrace PTRACE_TRACEME self-attach, timing
  deltas (clock_gettime / rdtsc); PE: IsDebuggerPresent +
  CheckRemoteDebuggerPresent + NtQueryInformationProcess
  (ProcessDebugPort). Response = SILENT CORRUPTION. Oracles stay
  clean-env (the checker never executes native binaries); anti-debug is
  itself ground truth: static signature scans on committed bytes +
  the documented local dynamic proof
  (`eval_native_targets.py --dynamic-proof <task>`, ptrace wrapper on
  Linux x86_64, structured SKIP elsewhere, CI skips).
- **L2 = OLLVM-STYLE flattening via a source-level python flattener**
  (honest label, `eval_native_sources.flatten_region`): the marked
  canonical loop becomes a switch dispatcher. Optimizer resistance is
  explicit and mechanical — `volatile` dispatcher state in C,
  package-level `//go:noinline` state accessors in Go, `noinline` stage
  helpers throughout — so the dispatcher cannot fold back under -O2/gc.
  Two regression faces pin it: `--flatten-check` (disassembly shape:
  the entry function's case compares against state values 1/2 exist at
  L2 and are absent at L1 — the raw .text-size heuristic is noisy under
  -Os and is recorded but not load-bearing) and `--self-check`
  (compile-and-execute: the generated source, per rung, must reproduce
  the seed model byte-exact; on linux/arm64 the committed .so itself is
  exercised via ctypes). r2 correction: the first cut of this section
  claimed flattened builds stay byte-exact without any execution
  evidence — false at the time (the arm stage hashing read uninitialized
  buffer bytes, and the C SHA padding split short messages into two
  blocks where the model pads to one); both are fixed and now guarded by
  the self-check face.

Checker/contract deltas (backward compatible): `TIERS += "release"`,
`EVAL_VERSIONS = ("eval-v1", "eval-v1.1")` (+ `EVAL_TIER_VERSION` map),
native families registered in `scripts/eval_native_targets.py`, the
checker resolves a family's registry from either module and renders
per-entry python harnesses (candidates are pure-python reimplementations
exposing the family entry, graded by constant-hit + pair-match over
published + checker-minted probes recomputed from the seed model —
stored nowhere). Toolchain-absent = structured SKIP on the mint side
(`toolchain_report`); the landed corpus never needs a toolchain to grade.
