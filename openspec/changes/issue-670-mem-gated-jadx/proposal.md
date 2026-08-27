# Proposal: memory-gated jadx dispatch — smali fallback for APK, REFUSE for JAR (#670)

## Problem

A 395MB APK with 12GB jadx heap thrashes through GC for ~10 hours before completing. Operationally that's a failed dispatch — kunglao's stuck-watchdog (STUCK_MINUTES=20) reclaims the slot.

Smali is Dalvik-only. A pure Java JAR has no smali fallback. When jadx is infeasible on a JAR, the analyzer MUST refuse — there is no analysis path.

## Calibration (single data point — refine with more samples)

- Source: 395MB APK, 12GB heap, ~10h GC-thrashed completion
- Formula: `est = max(4GB floor, 50 * sum(dex_bytes))`
- Budget: `0.65 * avail_gb` (stdlib mem: ctypes GlobalMemoryStatusEx on Windows, sysconf on POSIX)
- Verdict (APK/dex):
  - `budget >= 1.5*est` -> `jadx-ok` (full decompile)
  - `est <= budget < 1.5*est` -> `targeted-jadx` (baksmali xref first -> identify target classes -> jadx per-target only, memory bounded by target set)
  - `budget < est` -> `smali-only` (baksmali JSON xref/search + smali semantic analysis; no jadx)
- Verdict (JAR): `budget < est` -> `REFUSE` ("jadx-infeasible: pure Java has no smali fallback; analysis cannot proceed at this memory budget")
- Calibration basis declared in gate output: `calibration_basis: "single data point - refine with more samples"` (numeric-fidelity per #54)

## Out of scope

- Embedding-based APK similarity (APK-to-APK correlation)
- Native (.so) deobfuscation for Android (separable per existing #617 flow)
- Multi-sample calibration (one data point is current basis; need more real runs to tune factors)

## What changes

- **New `tools/static/apk_mem_gate.py`**: pre-dispatch estimator. Input = APK or jar path. Output = JSON `{apk_size, dex_count, dex_bytes_total, est_heap_gb, avail_gb, budget_gb, verdict, reason, calibration_basis}`. Always written to `evidence/apk_mem_gate.json` (operator-audit).
- **New `tools/static/baksmali_index.py`**: replaces gitnexus's role for DEX (gitnexus is Java-only). Calls `baksmali list --format json` for class/method enumeration; calls `baksmali xref` per relevant class for call graphs. Emits `evidence/smali_index.json` in same shape as gitnexus output — downstream convergence_check + worker contract don't need to know which tool indexed.
- **`scripts/toolchain.py`**: register `baksmali` T1 presence probe (jar path; install via `apt install baksmali` or Homebrew/jar download). FIXES + NextAction entry with URL embedded inline.
- **`scripts/convergence_check.py`**: gain `Event.JADX_INFEASIBLE` enum value (intake-level — fires from intake handler, NOT DRAIN; documented in the enum docstring as out-of-band).
- **`scripts/route_capability.py`**: gain trigger logic — `java/jar + budget < est -> REFUSE`; `android + apk -> apk_mem_gate -> (jadx|baksmali)`. The verdict from apk_mem_gate selects the downstream agent dispatch.
- **`scripts/kunglao-init.py`** android flow: at Phase 0 (after #669 apkid scan, before jadx dispatch), emit `evidence/apk_mem_gate.json` ALWAYS (operators audit the verdict even when jadx-ok).
- **Operator config** (`analysis_state.txt`):
  - `apk_mem_dex_factor=50` (default; was 2.5x, recalibrated)
  - `apk_mem_floor_gb=4`
  - `apk_mem_budget_ratio=0.65`
  - `apk_mem_override=jadx|baksmali|refuse` (operator escape hatch)

## Acceptance

- [ ] `tools/static/apk_mem_gate.py` writes `evidence/apk_mem_gate.json` with the documented schema; verdict = `jadx-ok|targeted-jadx|smali-only|refuse`.
- [ ] JAR target -> always REFUSE (no smali fallback).
- [ ] `tools/static/baksmali_index.py` produces `evidence/smali_index.json` schema-compatible with gitnexus output.
- [ ] `scripts/toolchain.py` registers `baksmali` T1 + `_STATIC_NEXT_ACTIONS`.
- [ ] `scripts/convergence_check.py` Event enum gains `JADX_INFEASIBLE` (doc'd as intake-level, NOT in DRAIN).
- [ ] `scripts/route_capability.py` gain memory-aware triggers.
- [ ] `tests/test_apk_mem_gate.py`: 8 RED -> GREEN cases (RED1 APK tiny -> jadx-ok, RED2 APK large -> smali-only, RED3 APK medium -> targeted-jadx, RED4 JAR -> REFUSE, RED5 dex_bytes_total sum correct, RED6 avail_gb detection, RED7 calibration_basis always populated, RED8 evidence JSON written even on REFUSE).
- [ ] `tests/test_baksmali_index.py`: 4 RED -> GREEN cases (RED1 missing baksmali binary -> noop + warning, RED2 schema shape, RED3 gitnexus-shape compat, RED4 fail-open on per-class xref failure).

## Related

- #663 anomaly detection (apk_mem_gate verdict is itself a fact; mem-pressure entries in anomaly detector).
- #662 hypothesis seed (smali_index.json feeds competitor_group candidates same way Java gitnexus output would).
- #634 loop cost burn (orthogonal — gate prevents the jadx-thrash cost; #634 covers general idle state).
- User directive "思考当前体系怎么最优的发挥作用" — baksmali_index.py is gitnexus's ROLE for DEX, not a parallel pipe (downstream reads the same JSON shape regardless of source).