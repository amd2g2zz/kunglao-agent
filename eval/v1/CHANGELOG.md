# eval-v1 changelog

## eval-v1.1 (#332 release tier — WEB/NET half)

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
