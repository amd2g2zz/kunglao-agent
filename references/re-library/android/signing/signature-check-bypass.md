---
name: signature-check-bypass
description: Countermeasure ladder for Android app self-integrity checks — read the resign-and-observe tell, identify which channel the check reads (PackageManager API, APK file bytes, or mutual dex/native attestation), then climb the spoof ladder from least invasive (framework-level signature spoof) to most invasive (native IO redirection serving original bytes at the file boundary). Use when a repackaged or resigned APK crashes at launch, shows a black screen, or hangs on the splash screen, or when a hook-based patch keeps getting defeated by a second copy of the check. Not for traffic pinning (stacked-protections), not for instrumentation/root/environment detection generally (anti-analysis), and not for recovering the signing algorithm itself (native-sign-recovery).
domain: android
family: signing
---

# Signature-check bypass (channel-matched spoof ladder)

Self-integrity checks compare an observed identity (signature bytes, APK
digest, file path) against an expected one. Every countermeasure below is
a hypothesis until behavioral verification: the app's own verdict must
flip (it runs, or the protected feature unlocks) with no new failure
surfaced — the same replay-gate philosophy as native-sign-recovery step 6.

## The tell (hypothesis, not fact)

Resign the repackaged APK with any key, install, launch: crash, black
screen, or permanent splash-hang **is consistent with** a signature check.
A minority of targets punish harder (wiped data, brick-class behavior on
some scamware) — treat destructive-punishment targets as one-shot: do the
static read first, spend installs deliberately.

## Where the check reads (acquisition channels)

**Family: environment-attestation reading (falsifier-library family 17 vocabulary — know the read to answer the read)**

| Channel | What the check does | Evidence | Variant inspiration |
|---|---|---|---|
| PackageManager API | `getPackageInfo(..., GET_SIGNATURES)` -> signature bytes -> digest -> compare against a baked-in constant | 1 article (full code) | Any API-served identity (installer source, first-install time) spoofs the same way |
| APK file bytes | Library or Java code opens the APK path (from `ApplicationInfo.sourceDir` or `/proc/self/maps`) and digests it — path varies per device, so the read usually starts from a path/lookup | 2 articles (device-side and emulation-side attestation) | File-identity checks generalize: any "expected bytes at expected path" check is answerable at the file layer |
| Mutual attestation ("triangle") | Native checks dex, a dynamically unpacked dex checks native, dex checks the unpacked dex — three reads, deleted after checking | 1 article | Mutual-attestation logic: single-point spoofs fail; every read channel needs a consistent answer |
| Behavior gates on failure | Kill process / exit / finish-only (activity fades but check re-fires after restart by the process watcher) | 1 article | Failure-action taxonomy tells you whether your bypass "took": a finish-only gate looks bypassed then re-arms |

## The spoof ladder (climb by invasiveness; stop at the first rung that verifies)

**Family: tamper-countermeasure escalation (verification-safety minimal-patch vocabulary — a bypass is a probe license, never a ship artifact)**

| Rung | Do this | Expected outcome (hypothesis) | Evidence | Variant inspiration |
|---|---|---|---|---|
| 1. Framework-level signature spoof | Deploy a framework-module signature-spoof (device/Xposed-class) and install the resigned APK without repack changes | App reads its *original* signature from the API channel; check passes untouched | 1 article | Answers every API-channel check at once; useless against file-byte checks |
| 2. Strip the check in smali/dex | Locate the verdict method, patch its body to return success | Cheap when the check is one method; mutates the package, so rung-3/4 checks may still fire | 1 article (tool-assisted class) | Binary-patch-and-verify pattern: patch, resign, observe — never assume the patch found every copy |
| 3. App-layer PackageManager proxy | Reflect to the runtime's package-manager holder, wrap the binder interface in a dynamic proxy whose handler swaps signature bytes for the original's, and patch **both** injection points (the holder's static field and the app-side manager's private field — call paths reach both) | App-layer readers see original signature; no package mutation survives | 1 article (full code, 2 injection points) | Binder-interface proxying generalizes to any system service identity the app reads |
| 4. Native IO redirection | Inline-hook the libc file-entry symbols (`open`, `openat`, `fopen`, and the variadic `syscall()` — raw syscall NRs bypass the libc wrappers, same SVC floor as dynamic-observation-ladders) plus `dlopen`-class if loads are checked; on path match, serve a preserved copy of the **original** APK's bytes; make the libc code page writable first (some builds protect it) | Native readers digest original bytes; also answers resource-read and some risk-counter reads | 1 article (full C code); emulation-side twin cross-cluster | Redirect capability triple: force read-only, deny with errno, replace path — reuse for root-detection file denials and startup-counter resets |
| 5. Original keystore | Sign with the developer's actual key | Only fully clean closure; usually unavailable | 1 article (listed, half in jest) | The existence of rung 5 is why rungs 1-4 spoof reads, not identities |

## Rung-selection heuristics

- **Match the rung to the read channel, not to habit**: rung 1 answers
  API-channel checks; file-byte checks need rung 4 (or a rung-3 variant
  that feeds the file read). Triangle attestation needs rung 4 consistency
  across all three reads.
- **Escalate only on a failed verification**, not on difficulty: if rung 1
  flips the behavior gate, stop.
- **Watch for re-arming gates**: a finish-only failure action means the
  check re-fires after the process watcher restarts the app — verify after
  a full restart cycle, not a single launch.
- **Preserve the original APK bytes before repacking** — rung 4 needs them,
  and offline reproduction targets (native-sign-recovery) need the same
  preserved input set.

## Cross-references

- Device-side detection families that co-deploy with these checks: [anti-analysis.md](../../anti-analysis/catalog/anti-analysis.md)
- Pinning and transport-layer identity checks: [stacked-protections.md](../protections/stacked-protections.md)
- Emulation-side answering of the same file reads: [unidbg-env-filling.md](../emulation/unidbg-env-filling.md)
- Minimal-patch rule and evidence vocabulary for verification harnesses: [verification-safety.md](../../method/process/verification-safety.md)
