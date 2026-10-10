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

| Channel | What the check does | Evidence to capture | Variant inspiration |
|---|---|---|---|
| PackageManager API | `getPackageInfo(..., GET_SIGNATURES)` -> signature bytes -> digest -> compare against a baked-in constant | The compare constant + failing read trace | Any API-served identity (installer source, first-install time) spoofs the same way |
| APK file bytes | Library or Java code opens the APK path (from `ApplicationInfo.sourceDir` or `/proc/self/maps`) and digests it — path varies per device, so the read usually starts from a path/lookup | The opened path string from the access log | File-identity checks generalize: any "expected bytes at expected path" check is answerable at the file layer |
| Mutual attestation ("triangle") | Native checks dex, a dynamically unpacked dex checks native, dex checks the unpacked dex — three reads, deleted after checking | Which read fires first | Mutual-attestation logic: single-point spoofs fail; every read channel needs a consistent answer |
| Behavior gates on failure | Kill process / exit / finish-only (activity fades but check re-fires after restart by the process watcher) | The gate action observed across restarts | Failure-action taxonomy tells you whether your bypass "took": a finish-only gate looks bypassed then re-arms |

## The spoof ladder (climb by invasiveness; stop at the first rung that verifies)

**Family: tamper-countermeasure escalation (verification-safety minimal-patch vocabulary — a bypass is a probe license, never a ship artifact)**

| Rung | Do this | Expected outcome (hypothesis) | Evidence to capture | Variant inspiration |
|---|---|---|---|---|
| 1. Framework-level signature spoof | Deploy a framework-module signature-spoof (device/Xposed-class) and install the resigned APK without repack changes | App reads its *original* signature from the API channel; check passes untouched | Verdict flip after install | Answers every API-channel check at once; useless against file-byte checks |
| 2. Strip the check in smali/dex | Locate the verdict method, patch its body to return success | Cheap when the check is one method; mutates the package, so rung-3/4 checks may still fire | Which copy was patched; whether a second copy re-arms | Binary-patch-and-verify pattern: patch, resign, observe — never assume the patch found every copy |
| 3. App-layer PackageManager proxy | Reflect to the runtime's package-manager holder, wrap the binder interface in a dynamic proxy whose handler swaps signature bytes for the original's (listing below); patch **both** injection points (the holder's static field and the app-side manager's private field — call paths reach both) | App-layer readers see original signature; no package mutation survives | Proxy hit log per read | Binder-interface proxying generalizes to any system service identity the app reads |
| 4. Native IO redirection | Inline-hook the libc file-entry symbols (`open`, `openat`, `fopen`, and the variadic `syscall()` — raw NRs bypass the libc wrappers) plus `dlopen`-class if loads are checked; on path match, serve a preserved copy of the **original** APK's bytes (listing below) | Native readers digest original bytes; also answers resource-read and some risk-counter reads | Hook fire log with matched paths | Redirect capability triple: force read-only, deny with errno, replace path — reuse for root-detection file denials |
| 5. Original keystore | Sign with the developer's actual key | Only fully clean closure; usually unavailable | — | The existence of rung 5 is why rungs 1-4 spoof reads, not identities |

### Rung-3 listing — PackageManager binder proxy (skeleton)

```java
// Adapt the holder field names to the target Android build — they drift
// across API levels; read them off the framework jar for the target.
Class<?> atClass = Class.forName("android.app.ActivityThread");
Object thread = atClass.getMethod("currentActivityThread").invoke(null);
Field pmField = atClass.getDeclaredField("sPackageManager");
pmField.setAccessible(true);
final Object rawPm = pmField.get(thread);

Class<?> iPm = Class.forName("android.content.pm.IPackageManager");
Object proxied = Proxy.newProxyInstance(iPm.getClassLoader(), new Class<?>[]{ iPm },
    (proxy, method, args) -> {
        if ("getPackageInfo".equals(method.getName()) && args != null && args.length >= 2
                && ((int) args[1] & PackageManager.GET_SIGNATURES) != 0) {
            return signedWithOriginal((String) args[0]);   // serve ORIGINAL signature bytes
        }
        try {
            return method.invoke(rawPm, args);
        } catch (InvocationTargetException e) {
            throw e.getCause();
        }
    });
pmField.set(thread, proxied);
// SECOND injection point: the app-side manager caches its own binder — patch
// that private field too, or one call path still reaches the raw interface.
```

### Rung-4 listing — libc IO redirection to original APK bytes (skeleton)

```c
// Hook lib: Dobby (documented C API). Cover open/openat/fopen AND the raw
// syscall() — raw NRs bypass the libc wrappers entirely (the SVC floor).
#include <dlfcn.h>
#include <string.h>

static const char *kRealApk = "/data/local/tmp/original.apk";  // preserved pre-repack
static const char *kResignedApk = "/data/app/…/base.apk";      // read the live path from the access log

static int (*orig_open)(const char *, int, ...);

static int my_open(const char *path, int flags, ...) {
    if (path != NULL && strcmp(path, kResignedApk) == 0) {
        return orig_open(kRealApk, flags);   // serve ORIGINAL bytes at the file boundary
    }
    return orig_open(path, flags);
}

__attribute__((constructor)) static void install(void) {
    void *handle = dlopen("libdobby.so", RTLD_NOW);
    int (*DobbyHook)(void *, void *, void **) = dlsym(handle, "DobbyHook");
    DobbyHook(dlsym(RTLD_DEFAULT, "open"), (void *) my_open, (void **) &orig_open);
    // repeat for openat / fopen / syscall; on hardened builds make the libc
    // code page writable first (some builds protect it).
}
```

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
