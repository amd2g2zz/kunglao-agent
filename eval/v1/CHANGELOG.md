# eval-v1 changelog

## eval-v1.3 (#356 toolflex tier — tool-combination flexibility)

- Corpus layout extended: `eval/v1/tasks/toolflex/` with 3 constructed
  units across three chain-width families (owner directive 2026-09-23:
  the ladder grades OUTCOMES; this family grades PATH CAPABILITY —
  select / chain / RE-ROUTE tool combinations). One seed per family
  (35601-35603), every constant synthetic and seeded:
  - `tf-chain2-py-v1` (K=2) — extract (peek|probe) -> fold
    (fold64|refold64); four valid combinations.
  - `tf-chain3-js-v1` (K=3) — unwrap (xtract|scan) -> keymix (mix|blend)
    -> emit (emit64|reemit64); eight valid combinations.
  - `tf-chain4-py-v1` (K=4) — open (unlock|peel) -> derive (sprout|
    distill) -> expand (weave|braid) -> seal (seal|cap); sixteen valid
    combinations.
- Pipeline parameters exist ONLY as a mod-crypto-encrypted blob (the
  #332 generator core); the blob key lives ONLY inside extract-tool
  sources; the final digest folds in a seeded odd constant that lives
  ONLY in final-stage tool sources. Stock-crypto naive completion fails
  by construction.
- Chain-necessity mint gate (the deception-smoke analog): a unit ships
  only if EVERY single-tool baseline FAILS — each toolbox tool alone
  (all others PATH-shadowed) + mechanical naive completion (stock
  sha256/sha1/md5 truncations, zero-state fold, and a raw-stdout echo
  face when the solo output already has the answer shape); every
  attempt is checker-graded and recorded in `manifest.json`
  (kunglao-eval-tf-manifest/1). Threat-model boundary documented in the
  manifest: execution-level necessity; source-reading reimplementation
  is a trace-visible path outside the gate's scope.
- Blocked-path variants (the flexibility measurement): one tool per
  minimal-chain role mechanically blocked via PATH shadowing
  (`scripts/eval_tf_shadow.py` — prepended shadow dir, honest-error fake
  tools carrying the KUNGLAO-TF-SHADOW marker, never silent no-ops).
  Arm-agnostic wiring: the shadow travels in the session ENVIRONMENT
  (bare/CC-default and kunglao-loop runners inherit PATH; no runner code
  change). Mint-time verification per variant: the shadow errors with
  the marker + nonzero rc AND the re-route chain (alternate
  implementers) still greens the checker. Known limitation, graded not
  denied: name-invocation blocking only — absolute-path invocation
  bypasses; the graders flag it (bypass_detected) and F2 reports a
  re-route-only headline (f2_reroute).
- Trace graders (`scripts/eval_tf_graders.py`, kunglao-eval-tf-scores/1
  + kunglao-eval-tf-aggregate/1): F1 solve per (unit x variant) from the
  checker verdict; F2 = solved(blocked)/solved(unblocked) per unit
  (f2_reroute excludes bypass solves); F3 coverage = successful tool
  uses cover every manifest-required role; F4 waste = failed invocations
  + superseded route switches + post-coverage churn (unknown exits never
  count). Extraction faces: stream-json session transcripts (tool_use
  events; pipelines split; tool_result is_error -> exit) and kunglao
  event ledgers (action=tool_call rows, the `tool` field).
- Task-unit schema: `toolflex` tier + `eval-v1.3` version enum
  (schemas/eval-task-v1.json + validator in scripts/eval_dataset.py,
  per-tier TIER_EVAL_VERSION map extended additively). Shared-contract
  coordination: TF families follow the per-driver mirror convention
  until unioned into #352's scripts/eval_contract.py FAMILY_CONTRACT at
  the dev merge-sync (suffix ".txt", target_surface "text"); the strict
  conformance test activates with the module.

## eval-v1.1 (#332 release tier — WEB/NET half + NATIVE ladder)

- Corpus layout extended: `eval/v1/tasks/release/` with 15 constructed
  units across four packaging-ladder families (ground truth by
  construction; every derivation core routes through the generator's
  MOD-CRYPTO cipher — a seed-mutated SHA-256 (8 H words + 64 K round
  constants) + RFC 2104 HMAC over it; stock-crypto candidates fail every
  pair by construction, the named anti-standard regression):
  - `web-pack-sign` — sign(request) -> signature (canonical: method +
    path + mod-sha(body) + seq) at l0 (readable) / l1 (minify +
    hex-ids + decoys) / l2 (javascript-obfuscator@5.8.0 STRONG preset) /
    l3 (VM-bytecode: a python transform compiles the compression to
    seed-mutated custom opcodes + a JS interpreter loop; a python
    verifier proves bytecode == model at every mint).
  - `net-verify-license` — challenge/response license protocol, client
    SDK sample in JS. response = HMAC(KDF(challenge, secret),
    canonical_payload), the KDF chained on mod-SHA. Oracle is
    SERVER-SIDE: the checker hosts a LOOPBACK-ONLY mock license server
    (bind ("127.0.0.1", 0), ephemeral port) and validates every session
    on published + checker-minted challenges. NO-EGRESS GUARANTEE: the
    base URL reaches the candidate via harness argv only — no host
    literal exists in any artifact or generated harness; the server
    binds loopback explicitly and is never exposed beyond it.
  - `req-sign` — canonical-request signing (method +
    ordered-headers-hash + body-sha + path; HMAC over mod-SHA). l1
    canonicalizes headers in the given order; l2 sorts header names
    (permuted header order -> identical signature). The ECDSA-p256
    variant was deliberately NOT taken: a node-crypto ECDSA core would
    be a stock-lib primitive, contradicting the binding mod-crypto
    addition (stock candidates MUST fail).
  - `mod-crypto-js` — the mod-crypto core itself as the family face;
    constant-hit armed at l1, honestly disarmed at l2 (rc4 stringArray)
    and l3 (VM bytecode) — behavior is the oracle there.
- Packaging-ladder rungs: l0 readable baseline; l1 generator-side
  minify+hex-ids+decoys (deterministic, re-mint byte-identical); l2
  javascript-obfuscator@5.8.0 STRONG preset (controlFlowFlattening 1,
  deadCodeInjection 0.5, stringArray rc4+rotate+shuffle 1,
  numbersToExpressions, splitStrings, transformObjectKeys,
  unicodeEscapeSequence, selfDefending) — BYTES are randomized by the
  tool (selfDefending/stringArray rotation), so l2 units are
  behavior-pinned, not byte-pinned; the committed artifact is the pinned
  face and a documented local proof (pretty-print -> module breaks)
  re-runs in the suite. l3 VM-bytecode rung (deterministic,
  re-mint byte-identical).
- Anti-debug (owner addition) stamped into EVERY JS artifact: debugger
  trap loops with seed-mutated guards, Date.now/performance.now timing
  canaries, console getter traps; trip response = SILENT WRONG OUTPUT
  (never an exception or log). Clean-env guarantee: traps never fire in
  a clean node env (no devtools), outputs stay deterministic. At l2 the
  STRONG preset buries even property strings (Date.now mints as
  Date[_0x..('<rc4>')]) — the static literal face applies to the
  generator-native rungs only; l2 ground truth is the behavioral proof,
  mirroring the honestly-disarmed constant-hit face.
- Task-unit schema: `release` tier + `eval-v1.1` version enum
  (schemas/eval-task-v1.json + validator in scripts/eval_dataset.py,
  per-tier TIER_EVAL_VERSION map; smoke stays eval-v1). Task resolution
  (`resolve_task_dir`) now spans tiers when called tier-less.
- Anti-digest-table faces: web-pack-sign/req-sign replay object-shaped
  request probes (published + checker-minted); net-verify-license mints
  fresh challenges per run (a canned response validates nothing).
- Cheat regressions per family land in tests/test_eval_release_332.py
  (digest-table, key-copy-without-canonicalization, stock-crypto,
  constant-response, forged-session).

### eval-v1.1 — the NATIVE half (additive to the WEB/NET half above)

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

