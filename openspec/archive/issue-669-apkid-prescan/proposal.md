# Proposal: apkid pre-scan at android intake (#669)

## Problem

RE analysis of an Android APK currently begins blind. We decompile with jadx but don't know upfront:
- **Packers**: the APK may be wrapped (Bangcle/Jiagu/Tencent Legu/APKProtect) - jadx of a packed APK yields obfuscated garbage and silently passes "all classes decompiled" while the actual code is in the encrypted DEX.
- **Compilers**: source provenance (R8/DexGuard/ProGuard/ART native) narrows investigation.
- **Obfuscators**: DexGuard/Allatori/Stringer transforms need a deobfuscation pass before any sensible RE.

APKiD is a T1-second YARA-based scanner that fingerprints all three categories from one scan. Output feeds RE **triage** (not chain-of-custody - no claim of "this APK is malware").

## Solution

Wire APKiD into the android intake at Phase 0: run `apkid scan --json <apk>` -> write `evidence/apkid.json`. The orchestrator's downstream consumers (hypothesis seeder, anomaly detector, route capability) read the tags as triage signals.

## Calibration basis

APKiD's machine output is deterministic per file (YARA rules + APK metadata). No calibration needed - single run per APK.

## Out of scope

- Deep unpacking of specific packers (downstream worker task; the apkid scan only flags, doesn't unpack).
- Decoding obfuscator-specific transforms (downstream - feeds the smali path when triggered, see #670).
- APK-to-APK similarity (embedding-based; defer).

## What changes

- `scripts/toolchain.py`: register `apkid` (T1 CLI presence probe - `apkid --version`); the existing FIXES + NextAction pattern gains the entry.
- `scripts/toolchain_install.py`: add pip install plan (`pip install apkid`).
- `scripts/mcp_probe.py` android MCP manifest: optionally register apkid MCP server (probe-only - registration is consent-driven per #408).
- `scripts/apkid_scanner.py` (NEW): thin CLI wrapper that runs `apkid scan --json <apk>`, parses the result, writes `evidence/apkid.json` with the schema: `{tool, version, target, scanned_at, findings: [{rule, category, description, matched_files}], summary: {packer, compiler, obfuscator, anti_vm, anti_debug, total}}`. Fail-open: apkid binary missing -> write `evidence/apkid.json` with `{"tool": "apkid", "status": "unavailable", "reason": "..."}`.
- `scripts/kunglao_init.py` android flow: Phase 0 invokes `apkid_scanner.run(workspace, apk_path)` AFTER packer pre-pass and BEFORE jadx dispatch. Output always written (operators audit the verdict even when no findings).
- `references/re-library/languages-platforms.md` android section: link apkid output keys (compiler/packer/obfuscator) into the existing hypothesis seed pathway (#662) as `competitor_group: pq-family` candidates - exact wiring is one `hypothesis_seeder` extension.

## Acceptance

- [ ] `apkid_scanner` writes `evidence/apkid.json` per the schema above.
- [ ] apkid missing -> `evidence/apkid.json` carries `status: unavailable` (not crash).
- [ ] `kunglao_init.py` android flow invokes the scanner at Phase 0.
- [ ] Toolchain check: apkid presence reported with the new entry; FIXES + NextAction populated.
- [ ] `tests/test_apkid_scanner.py`: 6 RED -> GREEN cases (RED1 happy-path JSON parse, RED2 missing-binary -> unavailable, RED3 non-APK input -> error, RED4 schema shape, RED5 toolchain probe registered, RED6 init-flow integration).

## Related

- #662 hypothesis seed (apkid tags -> pq-family candidates in competitor_group).
- #663 anomaly detection (apkid output is a structured fact; the anomaly detector's lexical baseline excludes obvious packer names like "Bangcle").
- #670 memory-gated jadx dispatch (apkid packer flag may force the smali-only branch upstream of jadx).