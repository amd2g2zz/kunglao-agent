---
name: stacked-protections
description: Protection dimensions — SSL pinning, RASP, obfuscation, certificate-or-parameter encryption — are orthogonal and stackable over any main analysis route; recognize each from static observables and clear them in observation-first order before analyzing the target algorithm. Includes the recon sequence and the model-vs-mechanical-tool division of labor for dispatching analysis steps. Use when hooks fail or die, captures come back empty, or a decompile stays unreadable and the cause may be a protection layer rather than the target's complexity.
---

# Stacked Protections (orthogonal layers over any route)

Pinning, RASP, obfuscation, and payload encryption are not competing
routes — they are independent dimensions that deploy on top of any main
lane (java-sign / native-sign / web). One target can stack all four.
Two working consequences: clearing one layer never implies the others
are absent, and the presence of any layer says nothing about the target
algorithm itself.

## When to Use

- Before starting the main analysis on a hardened target — run the
  protection recon sequence (few-shot below) first; it is cheap and the
  failure modes it prevents are expensive.
- When an observed failure does not match the hypothesis: hook dead,
  capture empty, decompile unreadable. Each symptom maps to a suspected
  layer before "the algorithm is hard" becomes the conclusion.

## The orthogonality table

| Dimension | Recognition (static, observable) | What it blocks | First countermeasure class |
|---|---|---|---|
| SSL pinning | `network_security_config.xml` pin-set entries; `CertificatePinner` / custom `TrustManager` / `SSLSocketFactory` subclasses; bundled `.cer`/`.bks` trust assets | Your view of the traffic — not the target | Bypass at the trust-decision seam |
| RASP | Environment checks (`su` paths, emulator props, build tags); instrumentation-scan strings (`frida`, `gum-js-loop`, `ptrace`, `xposed`); `Debug.isDebuggerConnected`, ptrace self-attach | Your instrumentation — the tool dies or the app degrades on attach | Neutralize the specific detector class |
| Obfuscation | Renamed identifiers (R8-class); flattened control flow (dispatcher + state variable); encrypted string tables; native obfuscation traits | Your static reading — not the runtime behavior | Classify the obfuscation type, then its matching recovery route |
| Certificate/parameter encryption | Payload or fields unreadable while the HTTP framing is plain (wire-format card classes 1–3) | The values you need to read or reproduce | In-app decrypt boundary hook |

## Order principle: observation first, analysis second

**Clear what blocks your observation before analyzing the target.**
Pinning stands between you and the traffic; RASP stands between you and
the process; obfuscation stands between you and the code. None of them
is the target. The cost asymmetry decides the order: protection work is
mechanical and bounded, algorithm analysis is the expensive half —
running it through a blocked observation wastes the expensive half.

Symptom → suspected layer, in this order, before "hard algorithm":

1. Attach fails, the process dies, or hooks silently never fire →
   RASP (it detected the instrumentation) — not "this function is
   protected against analysis".
2. MITM capture empty, handshake fails, or the app refuses the proxy →
   pinning — the traffic exists; the app rejects your observer.
3. Decompile unreadable → classify the obfuscation type first; a named
   obfuscation has a known route, "unreadable code" does not.
4. Only when the observation channel is clean does a remaining failure
   count as evidence about the target algorithm.

### Few-shot — protection recon sequence (synthetic sample)

```bash
# Run BEFORE the main analysis; each hit reorders the plan.
APK=./sample-release.apk      # synthetic path — replace per target

# 1. pin-set declared in the network security config?
unzip -p "$APK" res/xml/network_security_config.xml | grep -icE "pin-set|trust-anchors"

# 2. pinning classes wired in the dex?
grep -acE "CertificatePinner|checkServerTrusted|X509TrustManager" extracted/classes*.dex

# 3. instrumentation-detection strings in the native libs?
grep -aicE "frida|gum-js-loop|ptrace|xposed|emulator" extracted/lib/*/libtarget.so

# 4. obfuscation traits? (renamed top-level classes, dispatcher loops)
# A clean pass on 1-3 = green light for the main route.
# Any hit = clear that layer FIRST; the main route starts after it.
```

## Division of labor (model vs mechanical tools)

- **Model-suited**: semantic triage of decompiled code (which function
  is the signer); source-to-sink tracing through obfuscated code;
  false-positive filtering over scanner output; complex authentication
  logic reconstruction.
- **Mechanical-tool-suited**: pattern matching and signatures; manifest
  parsing; resource/asset extraction; certificate and pinning
  detection; first-pass recon enumeration.
- The split mirrors maker/checker: tools enumerate and match, the model
  assigns meaning and filters. Never spend model attention on what a
  grep returns in one line — and never trust a grep to do semantics.

## Cross-references

- Detector-class countermeasures (anti-debug / anti-DBI / anti-VM):
  [anti-analysis.md](anti-analysis.md#anti-dbi-dynamic-binary-instrumentation)
- Pinning bypass by invoking through the seam:
  [languages-platforms.md](languages-platforms.md#frida-android-certificate-pinning-bypass)
- Payload-encryption dimension detail (opaque-body triage):
  [wire-format-recognition.md](wire-format-recognition.md)
- The main route the layers stack onto:
  [native-sign-recovery.md](native-sign-recovery.md#the-boundary-first-ladder)
