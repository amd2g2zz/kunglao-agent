# method_families.derivation.md — the #432 mined vocabulary

> The registry (`scripts/method_families.yaml`) is CLOSED and MINED, not
> invented. This doc carries the per-family counts, sources and examples
> behind every token, so a registry extension is a reviewed diff against
> measured usage — never a seat-of-the-pants word. Mining sweep date:
> 2026-09-28.

## Q-key policy (restated from the registry header)

A method family names the **approach** (how the work attacks the claim).
Method family is the Q key — `Q(state signature, method family)`; the
**tool chain is a rider** that rides dispatch telemetry and may never
enter the key. `grep the constants` and `ghidra xref the constants` are
one family (`static-decompile` / `crypto-core-identification`), two
riders. Tool-family words that appear below appear only as mining
*evidence*, never as tokens.

## Mining corpus

| source | what it contributed |
|---|---|
| `/Users/mikenike/workprojects/kunglao-wt/eval-campaign-v016/runs/eval-campaign-v016/` — arms `loop-arm`, `cc-default`, `bare-arm-sweep`, `bare-k3`, `loop-arm-relaxed`, `loop-k3`, `dimgraders`/`dimgrades`; `shard-*/eval-results-*.json` + `workspaces/ws-*/` (`claim-register.yaml`, `facts/`, `runs/mission_ledger.yaml`, `runs/logs/kunglao-*.jsonl`) | the actually-used approach vocabulary: fact `source:`/`evidence_class:` fields, checker kinds, dispatch-row agent faces, task-family distribution |
| `scripts/route_capability.py` tags (= `tools/_INDEX.yaml` capability tags, 41 distinct) | tool-capability prefixes as corroborating evidence (`static:*`, `dynamic:*`, `crypto:*`, `js:*`, `ghidra:*`, `web:*`) |
| `references/` quickref taxonomy (`_index-method.md`, `_index-anti-analysis.md`, `_index-dynamic.md`, `re-library/web/labs/web-re-quickref.md` five sections, `re-library/method/process/falsifier-library.md`) | the documented methodology sections each token anchors to |

Corpus shape at sweep time: 141 eval-result rows across 8 task families;
11 analysis facts with frontmatter; 133 unified-log `dispatch` rows (78
worker-dispatch rows by agent; the rest are init scaffold/wire-up rows).

## Per-family mining table

| token | count | source | example |
|---|---|---|---|
| `structural-anchoring` | 3 prescan facts + 4 triage-class facts | campaign facts (`T1 prescan of libkdf.so`, `die.json+apkid.json` prescans; `F001-sample-identity`) | `loop-k3/a2-arm-kdf-l1` F001: ELF64 aarch64 DYN, single export `kdf_derive @0x7` |
| `static-decompile` | 8 fact rows (`source=static-decompile`) | campaign facts, `loop-k3/a3-net-verify-license-l1a-v1` F001–F006+F009, `a2-arm-kdf` F001 | F003: "standard SHA-256 with a fully mutated constant set" read straight from deobfuscated source |
| `dynamic-trace` | 2 fact rows (`source=dynamic-trace`) | campaign facts F007/F008 | F008: reimplementation replay-equivalence validated against the original artifact's live sessions |
| `obfuscation-peeling` | 25 task rows + 3 capability tags | `web-pack-sign` task family; `js:deobfuscate`/`js:unbundle`/`js:obfuscation-detect` | web-re-quickref sections 2–3: peel layers, index the recovered tree |
| `crypto-core-identification` | 31 task rows + F003 + 2 tools | `mod-crypto-js` (20) + `mod-crypto-native` (11); `cipher_identify`, `crypto-tool` | mutated-constant SHA-256 identification before any protocol claim |
| `kdf-chain-reconstruction` | 29 task rows + F004 | `arm-native-kdf` (17) + `win-pe-kdf` (12) | F004: `sk = H(H(H(secret ‖ challenge_bytes)))`, 32-byte output |
| `protocol-flow-reconstruction` | 43 task rows + F002 | `net-verify-license` (22) + `req-sign` (21) | F002: two POST round-trips and their exact JSON shapes |
| `anti-analysis-discrimination` | 13 task rows + F006 | `smc-x86` family; `references/_index-anti-analysis.md` | F006: tripped canary sends a length-derived decoy — the decoy is proven, not assumed |
| `replay-harness-verification` | 88 checker rows + F007/F008 | `checker_kind=replay-roundtrip` eval rows | rebuild offline, prove byte-equivalence against recorded pairs |
| `pair-match-verification` | 53 checker rows | `checker_kind=pair-match` eval rows | captured input/output pairs reground field-by-field |
| `red-team-verification` | 58 dispatch rows + 35 passthrough events | campaign logs: `agent=kunglao-redteam` ×42, `verdict-scorer` ×16; `drift_verifier_passthrough` ×35 | adversarial re-derivation before PROVEN promotion |
| `hypothesis-falsification` | 19 falsifier families | `references/re-library/method/process/falsifier-library.md` | every candidate enters with a named kill experiment |

Counts are row counts in the corpus faces named per family — they are
mining evidence for vocabulary admission, not usage telemetry (usage
telemetry starts accruing in `runs/method-family-log.jsonl` once the
#432 gate face ships; `--reindex` re-derives it replayably).

## Dispatch-agent faces observed (riders, not tokens)

`kunglao-redteam` 42, `verdict-scorer` 16, `web-re-worker` 12,
`kunglao-worker` 8 (78 worker-dispatch rows). These are WHO executed —
the tool-chain/agent rider dimension. Recorded per dispatch in the usage
row's `agent`/`tools` fields, never in the family token.

## Deliberately NOT tokens

- Tool names and capability tags (`ghidra:recon`, `static:disasm`,
  `crypto:decode`, …) — riders by policy.
- Task/target families (`web-pack-sign`, `req-sign`, `arm-native-kdf`, …)
  — they classify the TARGET, not the approach; a `req-sign` target can
  be attacked by static-decompile or dynamic-trace alike.
- Eval arms (`loop-arm`, `bare-k3`, `dimgraders`, …) — campaign
  configuration, not approach.
- `triage`/`decompile`/`dynamic` evidence classes — kept as mining
  evidence only; the tokens above are the approach-level aggregation of
  them.

## Promotion procedure

1. `python scripts/method_families.py --triage <ws>` — quarantine
   frequencies and candidates (same one-line seen ≥ 3 times).
2. Candidate accepted → add the token to `scripts/method_families.yaml`
   WITH a `mined:` citation and a new row in the per-family table above.
3. Registry diff goes through the normal review gate. No auto-promote,
   ever — the triage face is advisory by construction (pinned by
   `tests/test_method_families_432.py::test_triage_never_auto_promotes`).
