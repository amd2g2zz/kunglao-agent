# Design — apkid pre-scan at android intake (#669)

## D1. Where the scan runs (Phase 0 of the android intake)

`scripts/kunglao_init.py` android flow runs Phase 0 checks **before** jadx dispatch (the dispatch itself is gated by #670). Sequence:

1. **target alignment** (#455) - resolve target_object (apk / jar / dex).
2. **toolchain check** (#408/keeps) - apkid presence probe is one new entry in the FIXES + NextAction table.
3. **apkid scan** (NEW for #669) - `apkid_scanner.run(workspace, apk_path)`; ALWAYS writes `evidence/apkid.json`, even when apkid is unavailable (fail-open).
4. **apk_mem_gate** (#670) - runs after apkid (a packed APK should not even hit jadx).
5. **jadx dispatch** (#670 outcome) - full / targeted / smali-only / REFUSE.

The scan never blocks intake. The output is triage signal for the orchestrator's downstream consumers (hypothesis seeder, anomaly detector, route capability), not a verdict.

## D3. Schema for `evidence/apkid.json`

```yaml
tool: "apkid"
version: "2.1.5"
target: "<absolute-apk-path>"
scanned_at: "2026-08-25T12:34:56Z"
findings:
  - rule: "Bangcle"
    category: "packer"
    description: "string encryption + dynamic DEX loading"
    matched_files: ["classes.dex"]
summary:
  packer: ["Bangcle"]
  compiler: ["R8"]
  obfuscator: ["DexGuard"]
  anti_vm: []
  anti_debug: ["anti_debug"]
  total: 3
status: "ok"
reason: ""
```

`status: unavailable` carries `{tool: "apkid", status: "unavailable", reason: "<reason>", scanned_at: "..."}` - summary defaults to empty/null, findings `[]`. Operators audit this state and decide whether to install apkid post-hoc.

## D4. Tool registration (FIXES + NextAction + install plan)

- `scripts/toolchain.py` FIXES gains:
  ```
  "apkid": "install apkid: pip install apkid (or apkid-ai-cli for the MCP variant); verify `apkid --version`",
  ```
- `scripts/toolchain.py` `_STATIC_NEXT_ACTIONS` gains:
  ```
  "apkid": NextAction("install", "pip install apkid"),
  ```
- `scripts/toolchain_install.py` gains the pip plan for `apkid` (alongside the existing pefile / flare-floss entries).

## D5. Hypothesis seeder integration (#662 extension)

`scripts/hypothesis_seeder.py` reads `evidence/apkid.json` when present (after seeding the pq-family scaffolds). For each PQ whose id/question text contains "packer", "compiler", "obfuscator", or "anti" tokens, it appends an `H-NNN+1` hypothesis entry to the matching `competitor_group` with body `apkid:<category>:<rule>`.

This is the "思考当前体系怎么最优的发挥作用" wire: the apkid output feeds the EXISTING hypothesis pipeline, not a new pipe.

## D6. Fail-open layers

- apkid binary missing -> scanner catches `FileNotFoundError`, writes `status: unavailable`, never raises.
- apkid returns non-JSON or partial output -> scanner writes `status: error`, captures stderr in `reason`.
- `evidence/apkid.json` malformed when read by downstream -> existing fail-open paths in hypothesis_seeder / anomaly_detector apply (no schema-required crash).

## D7. Test strategy (RED-first)

- RED1 happy-path: synthetic apkid JSON -> `evidence/apkid.json` written with the schema fields populated; `summary` rolled up.
- RED2 missing-binary: `apkid` not on PATH -> `status: unavailable`, scanner returns 0, no crash.
- RED3 non-APK input: scanner refuses input that doesn't end in `.apk` (case-insensitive) -> `status: error`, scanner returns 1.
- RED4 schema shape: every required field present (`tool`, `version`?, `scanned_at`, `findings`, `summary`, `status`); `summary` keys (`packer`, `compiler`, `obfuscator`, `anti_vm`, `anti_debug`, `total`) always present (default `[]` / `0`).
- RED5 toolchain probe registered: `scripts/toolchain.py` exposes apkid in the FIXES dict + `_STATIC_NEXT_ACTIONS`.
- RED6 init-flow integration: `kunglao_init.py` android flow invokes `apkid_scanner.run` at Phase 0 (mocked; verified via monkeypatch).

## D8. Out of scope

- Embedding-based APK similarity (defer - different problem).
- Native (.so) deobfuscation for Android (separate pipeline #617).
- The "thinking system optimum" instruction means: integrate, don't add. The apkid output feeds existing pipes (hypothesis_seeder, anomaly_detector, route_capability) - no new pipeline introduced.