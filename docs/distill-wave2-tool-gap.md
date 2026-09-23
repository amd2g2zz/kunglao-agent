# Tool distillation wave 2 — capability filter addendum

Issue #359 companion to the wave-1 distillation catalog. Desensitized per the
source-protection policy: sources appear only as S1..S7 with license type and
retrieval date (2026-09-23). Every cleared capability below was REIMPLEMENTED
in-house from methodology understanding — no third-party code was vendored,
ported, or translated; all committed code is fresh, house-convention code.

Method: per source, inventory every code asset, then apply the three-valued
filter — (A) general tool → reimplement, (B) covered by our toolshelf → cite
ours, (C) case-specific → abandon with one line. Dedup against
`tools/_INDEX.yaml` (39 registered tools at branch-out) is mandatory before
any (A) verdict; the cap of ≤5 reimplementations is applied by ranking on
generality × gap vs shelf × eval-family relevance.

## Filter verdicts

| id | source asset (capability) | verdict | rationale / citation |
|----|---------------------------|---------|----------------------|
| S1-A1 | Node-VM sandbox execution of obfuscated JS + proxy-monitored property access → undefined-env-path diagnosis loop | **A — reimplemented** | `tools/web/js_env_diagnose.py` (tag `js:env-diagnose`); no shelf capability runs JS in a sandbox or diagnoses missing browser env |
| S1-A2 | BOM/fingerprint stub module corpus (navigator/screen/storage/…) | C — abandon | case-shaped fingerprint stub bodies; the *diagnosis* capability is S1-A1, stubs stay per-case work product |
| S1-A3 | browser-side SDK init-param capture loop | B — covered | web-re-worker + browser MCP face (camoufox capture workflow) |
| S2-B1 | obfuscator-family fingerprinting from content signals → per-family pass routing | **A — reimplemented** | merged with S6-F1 into `tools/web/js_obfuscation_detect.py` (tag `js:obfuscation-detect`) |
| S2-B2 | generic multi-pass AST deobfuscation pipeline (normalize/prune/flatten/inline/rename) | B — covered | registered `wakaru-unbundle` + `webcrack-deobfuscate` (tags `js:unbundle`, `js:deobfuscate`) |
| S2-B3 | site-family adapter passes (per-target scripts) | C — abandon | single-family case adapters; the *detection* side is S2-B1 |
| S2-B4 | deobfuscation residue metrics (string-array density, loop-switch, opcode chains, hex-id count) | A(over cap) — deferred | genuinely general, ranked below the top-5 cut line; residue deltas are partially observable via S2-B1 detect + existing triage verdicts |
| S2-B5 | browser-env collectors → generated env stub modules | C — abandon | stub *generation* is case work; collection exists via browser MCP |
| S2-B6 | captcha/verification solver scripts | C — abandon | provider-specific case scripts, out of scope |
| S3-C1 | captured-param cipher-shape identification (charset × length → family candidates + next-check hints) | **A — reimplemented** | `tools/crypto/cipher_identify.py` (tag `crypto:identify`); `crypto-tool` decodes known families but nothing on the shelf *classifies* an unknown captured param |
| S3-C2 | browser-context hook snippet generator (cookie/XHR/JSON/crypto taps) | A(over cap) — deferred | general; rank below cut; current face lives in the web-re-worker quickref methodology |
| S3-C3 | project baseline manifest hashing | B — covered | `capture-golden` (auxiliary) |
| S3-C4 | real-case scaffold/templates | C — abandon | case scaffolds per issue out-of-scope |
| S4-D1 | cipher identifier by output length + charset | **A — reimplemented** | same capability as S3-C1; one implementation covers both |
| S4-D2 | baseline-vs-patched probe export delta (intervention verdict) | A(over cap) — deferred | generalizable delta evaluator but bound to their probe schema; our evidence contract differs |
| S4-D3 | differential verification of candidate signer functions against captured I/O pairs (emit harness → apply verdict) | **A — reimplemented** | `tools/web/sign_candidate_verify.py` (tag `js:sign-verify`); closes the req-sign/web-pack-sign endgame gap |
| S4-D4 | 8-dimension crypto-candidate scoring over probe artifacts | C — abandon | bound to their artifact schemas; methodology stays in wave-1 cards |
| S4-D5 | evidence-graph builder | B — covered | `build_evidence_index` (pipelines) |
| S4-D6 | delivery scaffolds (proxy service / pentest-tool doc / JSRPC stub emitters) | C — abandon | delivery-pipeline case scaffolds |
| S4-D7 | source-level property-read tap instrumentor + hook registry | A(over cap) — deferred | overlaps S3-C2 family; conservative-tap idea folded into wave-2 few-shot notes |
| S4-D8 | quarantine/doctor/service/validation infra | C — abandon | their workspace infra; ours exists |
| S5-E1 | ART-layer generic in-memory DEX dump (Java + native interception, magic check, dedup) | **A — reimplemented** | `templates/frida/dex-dump-art.js.tmpl` (frida-shaped asset → template per house convention; VM-only) |
| S5-E2 | flag-gated phase-1 Android bypass (root/emulator/proxy/SSL/debug) | **A — reimplemented** | `templates/frida/android-bypass-phase1.js.tmpl` |
| S5-E3 | static APK packer/shell detection | B — covered | `apkid-prescan` (tag `android:packer-fingerprint`) |
| S5-E4 | JNI/native-bridge clue indexing over a decompiled tree | A(over cap) — deferred | genuine gap; ranked below the cut; candidate for a wave-3 |
| S5-E5 | endpoint/URL extraction from decompiled tree | B — covered | `binary-sweep` (`--kind url/domain`) + `jadx-decompile` |
| S5-E6 | secret scanning over decompiled tree | B — covered | `strings-classify` + `yara-scan`/`yara-gen` |
| S5-E7 | phase-runner / tool-loader / summarizer infra | C — abandon | their orchestration infra; ours exists |
| S6-F1 | obfuscation-technique inventory with confidence + routing recommendation | **A — reimplemented** | merged into `tools/web/js_obfuscation_detect.py` |
| S6-F2 | control-flow-flattening locate/report | B — covered | `jsvmp_triage` F2 loop-switch verdict (tag `web:triage`) |
| S6-F3 | unpack/decode-strings/string-array/opaque-predicate AST passes | B — covered | `wakaru-unbundle` + `webcrack-deobfuscate` |
| S6-F4 | statistical rename (humanify-style) | C — abandon | methodology retained at wave-1; their port is workflow-specific |
| S6-F5 | whole-tree restoration workflow (import graph / promote / quality gate) | C — abandon | their restored-tree delivery convention; ours is evidence-workspace shaped |
| S6-F6 | obfuscation test fixtures | B — covered | house tests use synthetic inline fixtures (no third-party bytes) |
| S7-G1 | VDM-SL contract define/verify/smt/DB/codegen skill suite | C — abandon | external-toolchain methodology, no reimplementable code asset; contract governance lives in references/contracts |
| S7-G2 | contract-complexity model routing | C — abandon | prompt-internal heuristic; our dispatch tiers cover the intent |
| S7-G3 | mutation-testing eval runners (data) | B — covered | repo eval infra; out of scope per issue |

## Tally

- Reimplemented (5 capabilities): S1-A1, S2-B1+S6-F1 (merged), S3-C1+S4-D1
  (merged), S4-D3, S5-E1+S5-E2 (template pair = one capability face).
- Deferred past the ≤5 cap (recorded for a possible wave 3): S2-B4, S3-C2,
  S4-D2, S4-D7, S5-E4.
- Deliberately reimplemented NOTHING from unlicensed sources' code shape;
  S1/S3/S6 carry no license — learning is methodology-level only.

## Few-shot landing status

- (a) CLI `--help` usage examples: landed in every new tool (mechanically
  pinned by the few-shot test).
- (b) Index example rows: landed as `tools/_INDEX.yaml` entries with copyable
  usage in the matching `tools/_index-<category>.md` contract blocks
  (mechanically pinned).
- (c) Wave-1 distillate cards: NOT YET LANDED in the repo at branch-out time
  (wave-1 PR still in flight). Per the merge rule, the "Tool" usage-example
  appends for those cards are deferred to merge-sync; on this branch the
  few-shots additionally land in the *existing* cards
  (`references/re-library/patterns/vm/vm-deobfuscation-routing.md`,
  `references/re-library/web/labs/web-re-quickref.md`) as additive sections.
