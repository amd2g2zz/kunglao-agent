#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_native_targets.py — #332 release-tier NATIVE families (eval-v1.1).

The native half of the eval ladder (issue #332): three REAL-binary
families plus the mod-crypto core family, all seeded by construction with
the owner's three binding additions baked in:

  arm-native-kdf     real Android arm64 .so via the NDK (exported
                     kdf_derive, mod-SHA counter KDF, seed-mutated
                     constants). Rungs L0 plain / L1 stripped / L2
                     OLLVM-STYLE flattening (source-level python
                     flattener — honest label, see eval_native_sources).
  win-pe-kdf         real Windows PE via Go (GOOS=windows GOARCH=amd64
                     CGO_ENABLED=0). Same rungs + L2p = genuine UPX
                     packing (upx on PATH). UPX/PE builds are
                     timestamp-nondeterministic, so mint verifies by
                     UNPACKING, not byte-identity, and records evidence
                     instead of committing an over-budget binary.
  smc-x86            x86_64 ELF freestanding C (clang -nostdlib, minimal
                     _start). The payload's .text is XOR-encrypted in the
                     image; the stub's decrypt is GATED on the anti-debug
                     checks (wrong key under a tracer -> canary miss ->
                     silent corruption).
  mod-crypto-native  the mod-crypto core as a standalone arm64 .so (the
                     core every family consumes; the SMC payload IS a
                     mod-crypto implementation). Rungs L1/L2 only — L0
                     would be stock crypto, which is exactly the
                     anti-standard regression.

Addition B (anti-debug on ALL native samples): TracerPid parse
(seed-masked needle), ptrace PTRACE_TRACEME self-attach, timing deltas
(clock_gettime / rdtsc; PE: IsDebuggerPresent +
CheckRemoteDebuggerPresent + NtQueryInformationProcess). Response =
SILENT CORRUPTION (wrong outputs under a debugger). Oracles stay
clean-env: the checker never executes the native binaries; anti-debug is
itself ground truth — static signature scans on committed bytes plus the
documented local dynamic proof (``--dynamic-proof``, ptrace wrapper on
Linux x86_64, structured SKIP everywhere else, CI skips).

Wire: candidates are pure-python reimplementations exposing the family
entry (kdf_derive / payload_derive / mod_kdf) that take 32 bytes and
return a lowercase-hex string; the checker drives published +
checker-minted probes recomputed from the seed model (stored nowhere).

Toolchain-absent = structured SKIP (``toolchain_report``); the landed
corpus never needs a toolchain to grade.

stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

import eval_crypto as xc
import eval_dataset as ds
import eval_native_sources as src
import eval_targets as tg

SCHEMA_TASK = tg.SCHEMA_TASK
SCHEMA_GROUND_TRUTH = tg.SCHEMA_GROUND_TRUTH
EVAL_VERSION = "eval-v1.1"
TIER = "release"

M32 = tg.M32
M64 = 0xFFFFFFFFFFFFFFFF

# family registry: seed + per-unit shape (mirrors eval_targets.FAMILIES)
FAMILY_SEEDS: dict[str, int] = {
    "arm-native-kdf": 33201,
    "win-pe-kdf": 33202,
    "smc-x86": 33203,
    "mod-crypto-native": 33204,
}

NATIVE_FAMILIES = tuple(FAMILY_SEEDS)

UNITS: list[dict] = [
    {"family": "arm-native-kdf", "rung": "l0", "task_id": "arm-kdf-l0"},
    {"family": "arm-native-kdf", "rung": "l1", "task_id": "arm-kdf-l1"},
    {"family": "arm-native-kdf", "rung": "l2", "task_id": "arm-kdf-l2"},
    {"family": "win-pe-kdf", "rung": "l0", "task_id": "win-kdf-l0"},
    {"family": "win-pe-kdf", "rung": "l1", "task_id": "win-kdf-l1"},
    {"family": "win-pe-kdf", "rung": "l2", "task_id": "win-kdf-l2"},
    {"family": "win-pe-kdf", "rung": "l2p", "task_id": "win-kdf-l2p"},
    {"family": "smc-x86", "rung": "l0", "task_id": "smc-x86-l0"},
    {"family": "smc-x86", "rung": "l1", "task_id": "smc-x86-l1"},
    {"family": "smc-x86", "rung": "l2", "task_id": "smc-x86-l2"},
    {"family": "mod-crypto-native", "rung": "l1", "task_id": "mod-crypto-l1"},
    {"family": "mod-crypto-native", "rung": "l2", "task_id": "mod-crypto-l2"},
]

FAMILIES: dict[str, dict] = {
    "arm-native-kdf": {
        "toolchain": "python3", "language": "c/arm64",
        "target": "target/libkdf.so", "entry": "kdf_derive",
        "kind": "pair-match", "oracles": ["constant-hit", "pair-match"],
        "thresholds": {"min_constant_hits": 5, "min_pair_ratio": 1.0},
        "space_bits": 256, "rungs": ["l0", "l1", "l2"],
    },
    "win-pe-kdf": {
        "toolchain": "python3", "language": "go/windows-amd64",
        "target": "target/sample_kdf.go", "entry": "kdf_derive",
        "kind": "pair-match", "oracles": ["constant-hit", "pair-match"],
        "thresholds": {"min_constant_hits": 5, "min_pair_ratio": 1.0},
        "space_bits": 256, "rungs": ["l0", "l1", "l2", "l2p"],
    },
    "smc-x86": {
        "toolchain": "python3", "language": "c/x86_64-freestanding",
        "target": "target/smc_payload.elf", "entry": "payload_derive",
        "kind": "pair-match", "oracles": ["constant-hit", "pair-match"],
        "thresholds": {"min_constant_hits": 5, "min_pair_ratio": 1.0},
        "space_bits": 384, "rungs": ["l0", "l1", "l2"],
    },
    "mod-crypto-native": {
        "toolchain": "python3", "language": "c/arm64",
        "target": "target/libmodcrypto.so", "entry": "mod_kdf",
        "kind": "pair-match", "oracles": ["constant-hit", "pair-match"],
        "thresholds": {"min_constant_hits": 5, "min_pair_ratio": 1.0},
        "space_bits": 512, "rungs": ["l1", "l2"],
    },
}

CANDIDATE_ENTRIES = {f: m["entry"] for f, m in FAMILIES.items()}

_ANCHORS = {
    "arm-native-kdf": {
        "goal_verbatim": (
            "Analyze the arm64 ELF shared object target/libkdf.so, recover "
            "the mutated mod-SHA constants and the KDF structure, and "
            "re-implement kdf_derive so it reproduces the reference outputs "
            "byte-exact on arbitrary inputs."),
        "success_criterion": (
            "A re-implementation carrying the recovered constants that "
            "reproduces every published and checker-minted probe "
            "(byte-exact hex), plus the constants embedded in the "
            "re-implementation source."),
        "verification_method": "reproduction",
    },
    "win-pe-kdf": {
        "goal_verbatim": (
            "Analyze the Windows PE (source: target/sample_kdf.go, build "
            "records in ground truth), recover the mutated mod-SHA "
            "constants, and re-implement kdf_derive byte-exact."),
        "success_criterion": (
            "A re-implementation carrying the recovered constants that "
            "reproduces every published and checker-minted probe "
            "(byte-exact hex)."),
        "verification_method": "reproduction",
    },
    "smc-x86": {
        "goal_verbatim": (
            "Analyze the freestanding x86_64 ELF target/smc_payload.elf "
            "(self-decrypting payload gated on anti-debug checks), recover "
            "the mod-crypto implementation, and re-implement "
            "payload_derive byte-exact."),
        "success_criterion": (
            "A re-implementation carrying the mutated constants that "
            "reproduces every published and checker-minted probe "
            "(byte-exact hex)."),
        "verification_method": "reproduction",
    },
    "mod-crypto-native": {
        "goal_verbatim": (
            "Analyze the arm64 shared object target/libmodcrypto.so (the "
            "mutated mod-crypto core: S-box permutation, mutated H/K), and "
            "re-implement mod_kdf byte-exact."),
        "success_criterion": (
            "A re-implementation carrying the mutated S-box and H/K "
            "constants that reproduces every published and checker-minted "
            "probe (byte-exact hex)."),
        "verification_method": "reproduction",
    },
}

_CANDIDATE_CONTRACT = {
    "arm-native-kdf": ("A Python module exposing kdf_derive(data: bytes) "
                       "-> str (lowercase hex, 64 bytes out = counter-mode "
                       "mod-SHA over the recovered constants)."),
    "win-pe-kdf": ("A Python module exposing kdf_derive(data: bytes) -> str "
                   "(lowercase hex, 64 bytes out = counter-mode mod-SHA "
                   "over the recovered constants)."),
    "smc-x86": ("A Python module exposing payload_derive(data: bytes) -> "
                "str (lowercase hex, 16 bytes out = the decrypted "
                "payload's mod-crypto transform)."),
    "mod-crypto-native": ("A Python module exposing mod_kdf(data: bytes) "
                          "-> str (lowercase hex, 16 bytes out = the "
                          "mod-crypto AES-of-digest transform)."),
}


# ------------------------------------------------------------ deterministic rng
def _u32(seed: int, lane: int) -> int:
    return tg._u32(seed, lane)


def _u64(seed: int, lane: int) -> int:
    return ((_u32(seed, lane) << 32) | _u32(seed ^ 0xDEADBEEF, lane)) & M64


# ------------------------------------------------------------------- configs
def derive_cfg(family: str, seed: int) -> dict:
    """The per-variant parameter set (ground truth by construction)."""
    if family not in FAMILIES:
        raise ValueError(f"unknown native family: {family}")
    cfg = {
        "seed": seed,
        "h": xc.mutated_h(seed),
        "k": xc.mutated_k(seed),
        "sbox": xc.mutated_sbox(seed),
        "rcon": xc.mutated_rcon(seed),
        # anti-debug (addition B) mutated detection strings / thresholds:
        # generous timing thresholds so the gate can never fire in a clean
        # oracle environment (it exists to fire under a debugger)
        "needle_key": (_u32(seed, 0xA11) & 0xFF) or 0x5A,
        "timing_iters": 1000 + (_u32(seed, 0xA12) % 9000),
        "timing_ns": 2_000_000_000 + (_u32(seed, 0xA13) % 3_000_000_000),
        "timing_tsc": 200_000_000 + (_u32(seed, 0xA14) % 800_000_000),
        "corrupt_mask": _u64(seed, 0xA15),
    }
    cfg["smc_key"] = [(_u32(seed, 0xA20 + i) & 0xFF) for i in range(16)]
    return cfg


def constants_public(family: str, cfg: dict) -> dict:
    """The graded constants (the static constant-hit face iterates these
    against the CANDIDATE source; the artifact byte-scan uses the same
    set where the artifact carries them raw)."""
    if family in ("arm-native-kdf", "win-pe-kdf", "smc-x86"):
        return {f"h0_{i}": cfg["h"][i] for i in range(4)} | {
            "k_0": cfg["k"][0]}
    return {"sbox_0": cfg["sbox"][0], "sbox_255": cfg["sbox"][255],
            "h0_0": cfg["h"][0], "h0_1": cfg["h"][1],
            "rcon_0": cfg["rcon"][0]}


# ------------------------------------------------------------------ models
def model_output(family: str, cfg: dict, i: int, x):
    """The reference model: the same function computes ground truth at
    mint and lets the checker recompute expected outputs at run time."""
    seed = cfg["seed"]
    data = bytes(x)
    if family in ("arm-native-kdf", "win-pe-kdf"):
        return xc.kdf_sha(seed, data, 2).hex()
    return xc.payload_transform(seed, data).hex()


def _probe_input(seed: int, lane: int) -> list[int]:
    v = _u64(seed, lane)
    data = bytearray()
    for k in range(4):
        data += ((_u64(seed ^ v, lane + k)) & M64).to_bytes(8, "big")
    return list(data)


def minted_probes(family: str, seed: int, count: int) -> list[dict]:
    """Checker-minted probes: fresh inputs derived from the variant seed
    (the anti-digest-table face); stored nowhere, recomputed by the
    checker at run time. Minted face takes i >= 100 (disjoint from the
    published 0..N-1 keys)."""
    return [{"i": 100 + k, "input": _probe_input(seed ^ 0x5EED, k + 1)}
            for k in range(count)]


def published_pairs(family: str, seed: int, count: int) -> list[dict]:
    cfg = derive_cfg(family, seed)
    return [{"i": k, "input": _probe_input(seed, k + 1),
             "out": model_output(family, cfg, k, _probe_input(seed, k + 1))}
            for k in range(count)]


PUBLISHED_COUNT = 8
MINTED_COUNT = 8


# ------------------------------------------------------- anti-debug ground truth
def _anti_debug_gt(family: str, cfg: dict) -> dict:
    needle = bytes(b ^ cfg["needle_key"] for b in b"TracerPid:")
    if family == "win-pe-kdf":
        return {
            "response": "silent-corruption",
            "signatures": ["IsDebuggerPresent", "CheckRemoteDebuggerPresent",
                           "NtQueryInformationProcess"],
            "scan_source": "artifact",
            "scan_hex": [b.hex() for b in
                         (b"IsDebuggerPresent", b"CheckRemoteDebuggerPresent",
                          b"NtQueryInformationProcess")],
            "dynamic_proof": ("run under a debugger; outputs diverge by "
                              "CORRUPT_MASK (documented local proof via "
                              "--dynamic-proof; CI skips)"),
        }
    return {
        "response": "silent-corruption",
        "signatures": ["/proc/self/status self-read (TracerPid parse)",
                       "ptrace PTRACE_TRACEME self-attach", "timing-delta"],
        "scan_source": "artifact",
        "scan_hex": [b"/proc/self/status".hex()],
        # honest note: the detection needle IS seed-masked at source level,
        # but both target compilers constant-fold `needle[i] ^ NEEDLE_KEY`
        # into immediate stores, so no masked-byte array survives into the
        # artifact; the stable byte-level IOC is the self-status path
        "needle_masked_at": "source-level",
        "needle_hex": needle.hex(),
        "dynamic_proof": ("run under a ptrace wrapper; outputs diverge by "
                          "CORRUPT_MASK (documented local proof via "
                          "--dynamic-proof; CI skips)"),
    }


def anti_debug_face(family: str, gt: dict, blob: bytes) -> list[str]:
    """Mechanical anti-debug ground-truth scan: which recorded signature
    byte patterns appear in the scanned bytes (masked needle recomputed
    from the recorded hex — no stock detection strings on disk)."""
    ad = gt["anti_debug"]
    hits = []
    for sig, pattern_hex in zip(ad["signatures"], ad["scan_hex"]):
        if bytes.fromhex(pattern_hex) in blob:
            hits.append(sig)
    return hits


# ------------------------------------------------------------- toolchains
def _env_home(env: dict | None) -> Path | None:
    """An explicit env dict is a SANDBOX: only its HOME is consulted
    (never the host's), so toolchain_absent tests stay honest."""
    if env is None:
        return Path.home()
    home = env.get("HOME")
    return Path(home) if home else None


def _which(prog: str, env: dict | None = None) -> str | None:
    if env is None:
        return shutil.which(prog)
    for d in env.get("PATH", "").split(os.pathsep):
        candidate = Path(d) / prog
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def find_ndk_clang(env: dict | None = None) -> str | None:
    """The exact NDK arm64 wrapper path (aarch64-linux-androidNN-clang,
    highest API number wins; the unnumbered wrapper as fallback)."""
    home_root = _env_home(env)
    if home_root is None:
        return None
    home = home_root / ".NDK" / "arm64" / "bin"
    if not home.is_dir():
        return None
    import re
    numbered = []
    for p in home.glob("aarch64-linux-android[0-9][0-9]-clang"):
        m = re.search(r"android(\d+)-clang$", p.name)
        if m:
            numbered.append((int(m.group(1)), str(p)))
    numbered.sort()
    if numbered:
        return numbered[-1][1]
    plain = home / "aarch64-linux-android-clang"
    return str(plain) if plain.is_file() else None


def find_lld(env: dict | None = None) -> str | None:
    """ld.lld for freestanding ELF links (the NDK ships one; host llvm
    may too). Absolute fallbacks only in the real environment."""
    if env is not None:
        return _which("ld.lld", env)
    for cand in ("/usr/local/opt/llvm/bin/ld.lld",):
        if Path(cand).is_file():
            return cand
    ndk = Path.home() / ".NDK" / "arm64" / "bin" / "ld.lld"
    if ndk.is_file():
        return str(ndk)
    return _which("ld.lld", env)


def find_strip(env: dict | None = None) -> str | None:
    if env is not None:
        return _which("llvm-strip", env) or _which("strip", env)
    for cand in ("/usr/local/opt/llvm/bin/llvm-strip",):
        if Path(cand).is_file():
            return cand
    return _which("llvm-strip", env) or _which("strip", env)


def toolchain_report(env: dict | None = None) -> list[dict]:
    """Structured toolchain availability (mint-side SKIP contract)."""
    rows = []
    ndk = find_ndk_clang(env)
    rows.append({"toolchain": "ndk-arm64",
                 "status": "OK" if ndk else "TOOLCHAIN_MISSING",
                 "path": ndk or ""})
    for name in ("go", "upx"):
        path = _which(name, env)
        rows.append({"toolchain": name,
                     "status": "OK" if path else "TOOLCHAIN_MISSING",
                     "path": path or ""})
    clang = _which("clang", env)
    lld = find_lld(env)
    rows.append({"toolchain": "clang",
                 "status": "OK" if clang else "TOOLCHAIN_MISSING",
                 "path": clang or ""})
    rows.append({"toolchain": "ld.lld",
                 "status": "OK" if lld else "TOOLCHAIN_MISSING",
                 "path": lld or ""})
    rows.append({"toolchain": "llvm-strip",
                 "status": "OK" if find_strip(env) else "TOOLCHAIN_MISSING",
                 "path": find_strip(env) or ""})
    return rows


# ------------------------------------------------------------------ builders
def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def _flatten_if_l2(text: str, rung: str, region: str, lang: str) -> str:
    if rung == "l2":
        return src.flatten_region(text, region, lang)
    return text


def build_arm_so(cfg: dict, rung: str, out_path: Path) -> dict:
    """REAL Android arm64 .so via the NDK wrapper (exact path discovered).
    L0 plain / L1 stripped / L2 flattened+stripped."""
    text = _flatten_if_l2(src.render_arm_c(cfg), rung, "rounds", "c")
    ndk = find_ndk_clang()
    if ndk is None:
        raise RuntimeError("TOOLCHAIN_MISSING: ndk-arm64")
    with tempfile.TemporaryDirectory(prefix="mint332-") as tmp:
        c_path = Path(tmp) / "kdf_arm.c"
        c_path.write_text(text, encoding="utf-8")
        so_path = Path(tmp) / "libkdf.so"
        proc = _run([ndk, "-shared", "-O2", "-Wl,--build-id=none",
                     "-o", str(so_path), str(c_path)])
        if proc.returncode != 0:
            raise RuntimeError(f"ndk build failed: {proc.stderr[-800:]}")
        strip = find_strip()
        if rung in ("l1", "l2") and strip:
            _run([strip, "--strip-all", str(so_path)])
        out_path.write_bytes(so_path.read_bytes())
    return {"build": f"ndk:{Path(ndk).name}", "rung": rung,
            "text_size": elf_text_size(out_path.read_bytes()),
            "flags": "-shared -O2 -Wl,--build-id=none"
                     + (" + strip --strip-all" if rung != "l0" else "")
                     + (" + source-level flattening" if rung == "l2" else "")}


def build_mod_so(cfg: dict, rung: str, out_path: Path) -> dict:
    text = _flatten_if_l2(src.render_mod_c(cfg), rung, "rounds", "c")
    ndk = find_ndk_clang()
    if ndk is None:
        raise RuntimeError("TOOLCHAIN_MISSING: ndk-arm64")
    with tempfile.TemporaryDirectory(prefix="mint332-") as tmp:
        c_path = Path(tmp) / "mod_crypto.c"
        c_path.write_text(text, encoding="utf-8")
        so_path = Path(tmp) / "libmodcrypto.so"
        proc = _run([ndk, "-shared", "-O2", "-Wl,--build-id=none",
                     "-o", str(so_path), str(c_path)])
        if proc.returncode != 0:
            raise RuntimeError(f"ndk build failed: {proc.stderr[-800:]}")
        strip = find_strip()
        if strip:
            _run([strip, "--strip-all", str(so_path)])
        out_path.write_bytes(so_path.read_bytes())
    return {"build": f"ndk:{Path(ndk).name}", "rung": rung,
            "text_size": elf_text_size(out_path.read_bytes()),
            "flags": "-shared -O2 -Wl,--build-id=none + strip"
                     + (" + source-level flattening" if rung == "l2" else "")}


def _elf_text_section(blob: bytes) -> tuple[int, int]:
    """(sh_addr, sh_offset) of .text in a 64-bit little-endian ELF."""
    shoff = struct.unpack_from("<Q", blob, 0x28)[0]
    shentsize = struct.unpack_from("<H", blob, 0x3A)[0]
    shnum = struct.unpack_from("<H", blob, 0x3C)[0]
    shstrndx = struct.unpack_from("<H", blob, 0x3E)[0]
    strtab_hdr = shoff + shstrndx * shentsize
    strtab_off = struct.unpack_from("<Q", blob, strtab_hdr + 0x18)[0]
    strtab_size = struct.unpack_from("<Q", blob, strtab_hdr + 0x20)[0]
    strtab = blob[strtab_off:strtab_off + strtab_size]
    for i in range(shnum):
        off = shoff + i * shentsize
        name_off = struct.unpack_from("<I", blob, off)[0]
        name = strtab[name_off:strtab.index(b"\x00", name_off)]
        if name == b".text":
            addr = struct.unpack_from("<Q", blob, off + 0x10)[0]
            offset = struct.unpack_from("<Q", blob, off + 0x18)[0]
            return addr, offset
    raise RuntimeError("ELF .text section not found")


def elf_text_size(blob: bytes) -> int:
    """sh_size of .text in a 64-bit little-endian ELF (the L2>L1
    flattening regression metric)."""
    shoff = struct.unpack_from("<Q", blob, 0x28)[0]
    shentsize = struct.unpack_from("<H", blob, 0x3A)[0]
    shnum = struct.unpack_from("<H", blob, 0x3C)[0]
    shstrndx = struct.unpack_from("<H", blob, 0x3E)[0]
    strtab_hdr = shoff + shstrndx * shentsize
    strtab_off = struct.unpack_from("<Q", blob, strtab_hdr + 0x18)[0]
    strtab_size = struct.unpack_from("<Q", blob, strtab_hdr + 0x20)[0]
    strtab = blob[strtab_off:strtab_off + strtab_size]
    for i in range(shnum):
        off = shoff + i * shentsize
        name_off = struct.unpack_from("<I", blob, off)[0]
        end = strtab.index(b"\x00", name_off)
        if strtab[name_off:end] == b".text":
            return struct.unpack_from("<Q", blob, off + 0x20)[0]
    raise RuntimeError("ELF .text section not found")


def _symbol_vaddr(blob: bytes, symbol: str) -> tuple[int, int]:
    """(value, size) of a defined function symbol from .symtab."""
    shoff = struct.unpack_from("<Q", blob, 0x28)[0]
    shentsize = struct.unpack_from("<H", blob, 0x3A)[0]
    shnum = struct.unpack_from("<H", blob, 0x3C)[0]
    shstrndx = struct.unpack_from("<H", blob, 0x3E)[0]
    strtab_hdr = shoff + shstrndx * shentsize
    strtab_off = struct.unpack_from("<Q", blob, strtab_hdr + 0x18)[0]
    strtab_size = struct.unpack_from("<Q", blob, strtab_hdr + 0x20)[0]
    strtab = blob[strtab_off:strtab_off + strtab_size]
    for i in range(shnum):
        off = shoff + i * shentsize
        name_off = struct.unpack_from("<I", blob, off)[0]
        end = strtab.index(b"\x00", name_off)
        if strtab[name_off:end] != b".symtab":
            continue
        sym_off = struct.unpack_from("<Q", blob, off + 0x18)[0]
        sym_size = struct.unpack_from("<Q", blob, off + 0x20)[0]
        link = struct.unpack_from("<I", blob, off + 0x28)[0]
        linked = shoff + link * shentsize
        str_off = struct.unpack_from("<Q", blob, linked + 0x18)[0]
        str_sz = struct.unpack_from("<Q", blob, linked + 0x20)[0]
        names = blob[str_off:str_off + str_sz]
        for s in range(sym_off, sym_off + sym_size, 24):
            st_name = struct.unpack_from("<I", blob, s)[0]
            st_info = blob[s + 4]
            st_value = struct.unpack_from("<Q", blob, s + 8)[0]
            st_size = struct.unpack_from("<Q", blob, s + 16)[0]
            end = names.index(b"\x00", st_name)
            if names[st_name:end] == symbol.encode() and st_info & 0xF == 2 \
                    and st_size > 0:
                return st_value, st_size
    raise RuntimeError(f"symbol {symbol} not found")


def build_smc_elf(cfg: dict, rung: str, out_path: Path) -> dict:
    """x86_64 freestanding ELF with a GENUINE SMC payload: payload.o is
    linked in, its .text bytes XOR-encrypted in place by the generator,
    the stub decrypts at run time gated on anti-debug. L0 plain/unstripped;
    L1 stripped; L2 payload source flattened before compile + stripped."""
    clang = _which("clang")
    lld = find_lld()
    strip = find_strip()
    if not (clang and lld):
        raise RuntimeError("TOOLCHAIN_MISSING: clang/ld.lld")
    payload_text = _flatten_if_l2(src.render_payload_c(cfg), rung,
                                  "rounds", "c")
    with tempfile.TemporaryDirectory(prefix="mint332-") as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "payload.c").write_text(payload_text, encoding="utf-8")
        obj = tmp_path / "payload.o"
        proc = _run([clang, "--target=x86_64-linux-gnu", "-ffreestanding",
                     "-fPIC", "-Os", "-c", str(tmp_path / "payload.c"),
                     "-o", str(obj)])
        if proc.returncode != 0:
            raise RuntimeError(f"payload compile failed: {proc.stderr[-800:]}")

        def link(stub_text: str, dest: Path) -> None:
            (tmp_path / "stub.c").write_text(stub_text, encoding="utf-8")
            proc = _run([clang, "--target=x86_64-linux-gnu", "-nostdlib",
                         "-static", "-O2", f"-fuse-ld={lld}",
                         "-Wl,--build-id=none", str(tmp_path / "stub.c"),
                         str(obj), "-o", str(dest)])
            if proc.returncode != 0:
                raise RuntimeError(f"stub link failed: {proc.stderr[-800:]}")

        def layout_of(blob: bytes) -> tuple[int, int, int]:
            vaddr, size = _symbol_vaddr(blob, "payload_entry")
            text_addr, text_off = _elf_text_section(blob)
            off = text_off + (vaddr - text_addr)
            tail = struct.unpack("<I", blob[off + size - 4:off + size])[0]
            return vaddr, size, tail

        # fixpoint: the stub embeds the payload's linked location as
        # immediate constants, so link -> measure -> re-render -> relink
        # until the layout stops moving (constant widths converge fast)
        guess_addr, guess_size, guess_tail = 0x401000, 0x1000, 0x5EED0000
        for _ in range(6):
            elf = tmp_path / "smc.elf"
            link(src.render_smc_stub(dict(cfg, payload_addr=guess_addr,
                                          payload_size=guess_size,
                                          payload_tail=guess_tail)), elf)
            blob = bytearray(elf.read_bytes())
            vaddr, size, tail = layout_of(blob)
            if (vaddr, size, tail) == (guess_addr, guess_size, guess_tail):
                break
            guess_addr, guess_size, guess_tail = vaddr, size, tail
        else:
            raise RuntimeError("payload layout did not converge")
        text_addr, text_off = _elf_text_section(blob)
        off = text_off + (vaddr - text_addr)
        clear = bytes(blob[off:off + size])
        key = bytes(cfg["smc_key"])
        for i in range(size):
            blob[off + i] ^= key[i % len(key)]
        if rung in ("l1", "l2") and strip:
            patched = tmp_path / "smc_patched.elf"
            patched.write_bytes(bytes(blob))
            proc = _run([strip, "--strip-all", str(patched)])
            out_path.write_bytes(patched.read_bytes())
        else:
            out_path.write_bytes(bytes(blob))
    return {"build": f"clang:{Path(clang).name}+ld.lld", "rung": rung,
            "payload_vaddr": vaddr, "payload_size": size,
            "text_size": elf_text_size(out_path.read_bytes()),
            "payload_sha256": hashlib.sha256(clear).hexdigest(),
            "flags": "-nostdlib -static -fuse-ld=lld -Wl,--build-id=none"
                     + (" + source-level flattening" if rung == "l2" else "")}


def pe_text_size(blob: bytes) -> int:
    """VirtualSize of the .text section in a PE32+ image (the win-face
    L2>L1 flattening regression metric, recorded at mint)."""
    e_lfanew = struct.unpack_from("<I", blob, 0x3C)[0]
    if blob[e_lfanew:e_lfanew + 4] != b"PE\x00\x00":
        raise RuntimeError("PE signature not found")
    nsec = struct.unpack_from("<H", blob, e_lfanew + 6)[0]
    opt = struct.unpack_from("<H", blob, e_lfanew + 20)[0]
    table = e_lfanew + 24 + opt
    for i in range(nsec):
        off = table + i * 40
        name = blob[off:off + 8].rstrip(b"\x00")
        if name == b".text":
            return struct.unpack_from("<I", blob, off + 8)[0]
    raise RuntimeError("PE .text section not found")


def _scan_constants(blob: bytes, constants: dict) -> dict:
    hits = {}
    for name, value in constants.items():
        forms = [f"{value:08x}".encode(), f"{value:016x}".encode(),
                 str(value).encode(),
                 (value & M32).to_bytes(4, "little")]
        hits[name] = any(f in blob for f in forms)
    return hits


def build_win(cfg: dict, rung: str, source_path: Path,
              constants: dict) -> tuple[str, dict]:
    """REAL Windows PE via Go; the exe is NOT committed (a Go PE cannot
    meet the <200KB committed-artifact budget — even UPX-packed floors
    sit around 400KB) — mint records the build + constant/anti-debug
    evidence instead. L2p = genuine UPX packing, verified by unpacking
    (never byte-identity: PE timestamps make packed bytes unstable)."""
    go = _which("go")
    if go is None:
        raise RuntimeError("TOOLCHAIN_MISSING: go")
    text = _flatten_if_l2(src.render_go_win(cfg), rung, "rounds", "go")
    source_path.write_text(text, encoding="utf-8")
    env = dict(os.environ, GOOS="windows", GOARCH="amd64",
               CGO_ENABLED="0")
    with tempfile.TemporaryDirectory(prefix="mint332-") as tmp:
        exe = Path(tmp) / "sample_kdf.exe"
        ldflags = "-s -w -buildid=" if rung != "l0" else "-buildid="
        proc = _run([go, "build", "-trimpath",
                     "-ldflags", ldflags, "-o", str(exe),
                     str(source_path)], env=env)
        if proc.returncode != 0:
            raise RuntimeError(f"go build failed: {proc.stderr[-800:]}")
        image = exe.read_bytes()
        record = {
            "goos": "windows", "goarch": "amd64",
            "cgo_enabled": 0, "ldflags": ldflags,
            "magic": "MZ",
            "size": len(image),
            "pe_text_size": pe_text_size(image),
            "sha256": hashlib.sha256(image).hexdigest(),
            "constant_hits": _scan_constants(image, constants),
            "not_committed_because": (
                "real Go PE exceeds the 200KB committed-artifact budget "
                "even UPX-packed; mint records build evidence instead"),
        }
        if rung == "l2p":
            upx = _which("upx")
            if upx is None:
                raise RuntimeError("TOOLCHAIN_MISSING: upx")
            packed = Path(tmp) / "sample_kdf_packed.exe"
            unpacked = Path(tmp) / "sample_kdf_unpacked.exe"
            proc = _run([upx, "--best", "-o", str(packed), str(exe)])
            if proc.returncode != 0:
                raise RuntimeError(f"upx pack failed: {proc.stderr[-400:]}")
            test_ok = _run([upx, "-t", str(packed)]).returncode == 0
            unpack_ok = _run([upx, "-d", "-o", str(unpacked),
                              str(packed)]).returncode == 0
            upacked_image = unpacked.read_bytes() if unpack_ok else b""
            record["upx"] = {
                "packed": True,
                "test_ok": test_ok,
                "unpack_ok": unpack_ok,
                "packed_size": packed.stat().st_size,
                "packed_sha256": hashlib.sha256(
                    packed.read_bytes()).hexdigest(),
                "unpacked_size": len(upacked_image),
                "unpacked_sha256": hashlib.sha256(upacked_image).hexdigest(),
                "unpacked_constant_hits": _scan_constants(
                    upacked_image, constants),
                "nondeterminism": "pe-timestamp",
                "note": ("UPX/PE builds are timestamp-nondeterministic: "
                         "mint verifies by unpacking, never byte-identity"),
            }
    return text, record


# --------------------------------------------------------- reference renderer
def render_reference_py(family: str, cfg: dict) -> str:
    """Self-contained pure-python reimplementation (the perfect-candidate
    self-check and the reference arm for the tier run)."""
    seed = cfg["seed"]
    h = "\n    ".join(f"0x{v:08x}," for v in cfg["h"])
    k_rows = [", ".join(f"0x{v:08x}" for v in cfg["k"][i:i + 4])
              for i in range(0, 64, 4)]
    k = "\n    ".join(row + "," for row in k_rows)
    common = f'''# reference.py — {family} reference re-implementation (#332).
# Self-contained pure python; byte-exact against the seeded model.
_M32 = 0xFFFFFFFF
_M64 = 0xFFFFFFFFFFFFFFFF
MOD_H = [
    {h}
]
MOD_K = [
    {k}
]


def _rotr(x, n):
    return ((x >> n) | (x << (32 - n))) & _M32


def _sha_blocks(msg):
    bit_len = (len(msg) * 8) & _M64
    padded = msg + b"\\x80" + b"\\x00" * ((55 - len(msg)) % 64) + \\
        bit_len.to_bytes(8, "big")
    return [padded[i * 64:i * 64 + 64] for i in range(len(padded) // 64)]


def mod_sha256(msg):
    h = list(MOD_H)
    for block in _sha_blocks(msg):
        w = [int.from_bytes(block[i * 4:i * 4 + 4], "big") for i in range(16)]
        for i in range(16, 64):
            s0 = _rotr(w[i - 15], 7) ^ _rotr(w[i - 15], 18) ^ (w[i - 15] >> 3)
            s1 = _rotr(w[i - 2], 17) ^ _rotr(w[i - 2], 19) ^ (w[i - 2] >> 10)
            w.append((w[i - 16] + s0 + w[i - 7] + s1) & _M32)
        a, b, c, d, e, f, g, hh = h
        for i in range(64):
            s1 = _rotr(e, 6) ^ _rotr(e, 11) ^ _rotr(e, 25)
            ch = (e & f) ^ (~e & g)
            t1 = (hh + s1 + ch + MOD_K[i] + w[i]) & _M32
            s0 = _rotr(a, 2) ^ _rotr(a, 13) ^ _rotr(a, 22)
            maj = (a & b) ^ (a & c) ^ (b & c)
            t2 = (s0 + maj) & _M32
            hh, g, f, e = g, f, e, (d + t1) & _M32
            d, c, b, a = c, b, a, (t1 + t2) & _M32
        h = [(x + y) & _M32 for x, y in zip(h, [a, b, c, d, e, f, g, hh])]
    return b"".join(x.to_bytes(4, "big") for x in h)
'''
    if family in ("arm-native-kdf", "win-pe-kdf"):
        entry = FAMILIES[family]["entry"]
        return common + f'''


def kdf_sha(data, blocks=2):
    out = bytearray()
    for j in range(blocks):
        out += mod_sha256(data + j.to_bytes(4, "little"))
    return bytes(out)


def {entry}(data):
    """{family}: counter-mode mod-SHA KDF (seed {seed})."""
    return kdf_sha(bytes(data), 2).hex()
'''
    sbox = ", ".join(f"0x{b:02x}" for b in cfg["sbox"]) + ","
    rcon = ", ".join(f"0x{b:02x}" for b in cfg["rcon"]) + ","
    entry = FAMILIES[family]["entry"]
    return common + f'''

MOD_SBOX = [{sbox}]
MOD_RCON = [{rcon}]


def _xtime(a):
    a <<= 1
    return (a ^ 0x1b) & 0xFF if a & 0x100 else a


def _aes_expand(key):
    words = [list(key[i * 4:i * 4 + 4]) for i in range(4)]
    for i in range(4, 44):
        t = list(words[i - 1])
        if i % 4 == 0:
            t = t[1:] + t[:1]
            t = [MOD_SBOX[b] for b in t]
            t[0] ^= MOD_RCON[i // 4 - 1]
        words.append([words[i - 4][j] ^ t[j] for j in range(4)])
    return [b for w in words for b in w]


def mod_aes128(block, key):
    rk = _aes_expand(key)
    s = [block[i] ^ rk[i] for i in range(16)]
    for rnd in range(10):
        s = [MOD_SBOX[b] for b in s]
        s = [s[(i + 4 * (i % 4)) % 16] for i in range(16)]
        if rnd < 9:
            for c in range(4):
                a0, a1, a2, a3 = s[4*c:4*c+4]
                s[4*c] = _xtime(a0) ^ _xtime(a1) ^ a1 ^ a2 ^ a3
                s[4*c+1] = a0 ^ _xtime(a1) ^ _xtime(a2) ^ a2 ^ a3
                s[4*c+2] = a0 ^ a1 ^ _xtime(a2) ^ _xtime(a3) ^ a3
                s[4*c+3] = _xtime(a0) ^ a0 ^ a1 ^ a2 ^ _xtime(a3)
        off = (rnd + 1) * 16
        s = [s[i] ^ rk[off + i] for i in range(16)]
    return bytes(s)


def mod_kdf_inner(data):
    digest = mod_sha256(bytes(data))
    return mod_aes128(digest[16:32], digest[0:16])


def {entry}(data):
    """{family}: the mod-crypto transform (seed {seed})."""
    return mod_kdf_inner(bytes(data)).hex()
'''


# ---------------------------------------------------------------- unit minting
def _smc_gt_record(cfg: dict, meta: dict, out_path: Path) -> dict:
    """SMC ground-truth record: the encrypted payload blob (committed
    bytes), the seed key, and the decrypted-payload digest — so the
    static face can verify constants exist in the CLEAR payload without
    the artifact carrying them raw."""
    blob = out_path.read_bytes()
    vaddr, size = int(meta["payload_vaddr"]), int(meta["payload_size"])
    text_addr, text_off = _elf_text_section(blob)
    payload = blob[text_off + (vaddr - text_addr):
                   text_off + (vaddr - text_addr) + size]
    key = bytes(cfg["smc_key"])
    return {
        "payload_hex": payload.hex(),
        "xor_key": key.hex(),
        "decrypted_sha256": meta["payload_sha256"],
        "note": ("smc units verify constants on the DECRYPTED payload "
                 "record, not raw artifact bytes (the payload is "
                 "encrypted in the image — that is the mechanic)"),
    }


def build_task_unit(family: str, rung: str, task_id: str | None = None):
    """Everything one release unit needs, in memory (except the native
    artifact, which the build produces)."""
    meta = FAMILIES[family]
    seed = FAMILY_SEEDS[family]
    task_id = task_id or f"{family.split('-')[0]}-ladder-{rung}"
    cfg = derive_cfg(family, seed)
    constants = constants_public(family, cfg)
    published = published_pairs(family, seed, PUBLISHED_COUNT)
    task = {
        "schema": SCHEMA_TASK,
        "task_id": task_id,
        "eval_version": EVAL_VERSION,
        "tier": TIER,
        "source": "constructed",
        "family": family,
        "seed": seed,
        "anchors": dict(_ANCHORS[family]),
        "workspace_scaffold": {
            "language": meta["language"],
            "files": [meta["target"], "reference.py"],
            "entry": meta["target"],
            "candidate_contract": _CANDIDATE_CONTRACT[family],
        },
        "checker": {
            "kind": meta["kind"],
            "oracles": list(meta["oracles"]),
            "entrypoint": "checker.py",
            "self_check_candidate": "reference.py",
            "metrics": ["ttc_seconds", "dispatch_count",
                        "pass_at_k_contribution", "converged"],
            "thresholds": dict(meta["thresholds"]),
        },
        "ground_truth": {"file": "ground_truth.json",
                         "space_bits": meta["space_bits"]},
        "contamination": {
            "held_out": True,
            "distiller_excluded": True,
            "provenance": "constructed",
        },
    }
    ground_truth = {
        "schema": SCHEMA_GROUND_TRUTH,
        "task_id": task_id,
        "family": family,
        "seed": seed,
        "rung": rung,
        "constants": constants,
        "space_bits": meta["space_bits"],
        "published_pairs": published,
        "minted_probe_count": MINTED_COUNT,
        "anti_debug": _anti_debug_gt(family, cfg),
        "note": (f"{family} rung {rung}: native artifact minted from seed "
                 f"{seed}; candidates are pure-python reimplementations "
                 f"({meta['entry']}); checker-minted probes defeat "
                 "digest-table copying"),
    }
    if family != "win-pe-kdf":
        ground_truth["constants_record_mode"] = "raw-bytes"
    return {"task": task, "ground_truth": ground_truth, "cfg": cfg,
            "constants": constants, "meta": meta}


def write_task_unit(family: str, rung: str, task_id: str,
                    root: Path, timing: dict | None = None) -> Path:
    """Mint one release unit onto disk: task.yaml + ground truth + checker
    shim + target artifact(s) + reference candidate. Idempotent."""
    unit = build_task_unit(family, rung, task_id)
    cfg, meta = unit["cfg"], unit["meta"]
    tdir = Path(root) / task_id
    (tdir / "target").mkdir(parents=True, exist_ok=True)
    started = time.time()

    artifact_sha = {}
    build_record = None
    smc_record = None
    if family == "win-pe-kdf":
        text, build_record = build_win(cfg, rung, tdir / meta["target"],
                                       unit["constants"])
    else:
        out_path = tdir / meta["target"]
        if family == "arm-native-kdf":
            build_meta = build_arm_so(cfg, rung, out_path)
        elif family == "mod-crypto-native":
            build_meta = build_mod_so(cfg, rung, out_path)
        else:
            build_meta = build_smc_elf(cfg, rung, out_path)
            smc_record = _smc_gt_record(cfg, build_meta, out_path)
        artifact_sha[meta["target"]] = hashlib.sha256(
            out_path.read_bytes()).hexdigest()

    (tdir / "reference.py").write_text(
        render_reference_py(family, cfg), encoding="utf-8")
    gt = unit["ground_truth"]
    gt["artifact_sha256"] = artifact_sha
    if family != "win-pe-kdf":
        gt["artifact_text_size"] = {
            meta["target"]: build_meta["text_size"]}
    if build_record is not None:
        gt["build_record"] = build_record
        gt["constants_record_mode"] = (
            "build-record (upx-unpacked)" if rung == "l2p"
            else "build-record")
        if rung == "l2p":
            gt["upx_record"] = build_record["upx"]
    if smc_record is not None:
        # constants stay raw-bytes (the payload's mutation tables live in
        # .rodata, unencrypted — only the payload CODE is SMC-encrypted);
        # the record pins payload integrity for the decrypt face
        gt["smc_record"] = smc_record
    if timing is not None:
        # build wall-clock is mint telemetry (stdout), never ground truth:
        # the corpus re-mints byte-identically from the seed
        timing[task_id] = round(time.time() - started, 1)

    (tdir / "task.yaml").write_text(
        yaml.safe_dump(unit["task"], sort_keys=False, allow_unicode=True),
        encoding="utf-8")
    (tdir / "ground_truth.json").write_text(
        json.dumps(gt, indent=2) + "\n", encoding="utf-8")
    shim = (
        "#!/usr/bin/env python3\n"
        f"# checker.py — {task_id} mechanical-checker shim (#332).\n"
        "# Standalone entry: delegates to the shared mechanical checker.\n"
        "# Default candidate is the unit's reference.py (self-check);\n"
        "# pass --candidate to grade an arm's re-implementation.\n"
        "import sys\n"
        "from pathlib import Path\n"
        "\n"
        "_HERE = Path(__file__).resolve().parent\n"
        "_SCRIPTS = _HERE.parents[4] / \"scripts\"\n"
        "if str(_SCRIPTS) not in sys.path:\n"
        "    sys.path.insert(0, str(_SCRIPTS))\n"
        "\n"
        "import eval_checker\n"
        "\n"
        "if __name__ == \"__main__\":\n"
        "    argv = sys.argv[1:]\n"
        "    if not any(a == \"--candidate\" or a.startswith(\"--candidate=\")\n"
        "               for a in argv):\n"
        "        argv += [\"--candidate\", str(_HERE / \"reference.py\")]\n"
        "    raise SystemExit(eval_checker.main([\"--task\", str(_HERE)]\n"
        "                                       + argv))\n")
    shim_path = tdir / "checker.py"
    shim_path.write_text(shim, encoding="utf-8")
    shim_path.chmod(0o755)
    return tdir


# ------------------------------------------------------------- dynamic proof
def run_dynamic_proof(task_id: str) -> int:
    """The documented LOCAL dynamic proof (addition C): run the smc ELF
    under a ptrace wrapper (strace) and show the silent corruption.
    Linux x86_64 only — every other platform degrades to a structured
    SKIP (exit 3), and CI skips it. Never fires in the checker."""
    tdir = None
    for base in (ds.EVAL_ROOT / "v1" / "tasks" / "release",):
        candidate = base / task_id
        if (candidate / "task.yaml").is_file():
            tdir = candidate
            break
    if tdir is None:
        print(f"FAILURE code=BAD_TASK detail=unknown task {task_id!r}")
        print("VERDICT REFUSED")
        return 2
    if sys.platform != "linux" or platform.machine() not in ("x86_64",
                                                             "amd64"):
        print(f"SKIP dynamic-proof {task_id}: requires linux x86_64 "
              f"(got {sys.platform}/{platform.machine()}); CI skips this "
              "proof by design")
        return 3
    strace = shutil.which("strace")
    if strace is None:
        print("SKIP dynamic-proof: no ptrace wrapper (strace) available")
        return 3
    task = ds.load_task(tdir)
    gt = json.loads((tdir / task["ground_truth"]["file"])
                    .read_text(encoding="utf-8"))
    elf = tdir / task["workspace_scaffold"]["entry"]
    probe = bytes(gt["published_pairs"][0]["input"])
    expected = gt["published_pairs"][0]["out"]
    clean = subprocess.run([str(elf)], input=probe, capture_output=True,
                           timeout=30)
    traced = subprocess.run([strace, "-f", str(elf)], input=probe,
                            capture_output=True, timeout=30)
    clean_hex, traced_hex = clean.stdout.hex(), traced.stdout.hex()
    print(f"METRIC clean_matches_model={int(clean_hex == expected)}")
    print(f"METRIC traced_corrupted={int(traced_hex != clean_hex)}")
    ok = clean_hex == expected and traced_hex != clean_hex
    print(f"VERDICT {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


# ------------------------------------------------------- artifact==model face
_SELF_CHECK_SHAPES = {
    "smc-x86": {
        "proto": "void payload_entry(const unsigned char *, unsigned char *);",
        "call": "payload_entry(in, out);",
        "out": 16,
    },
    "arm-native-kdf": {
        "proto": ("void kdf_derive(const unsigned char *, unsigned int, "
                  "unsigned char *, unsigned int);"),
        "call": "kdf_derive(in, 32u, out, 64u);",
        "out": 64,
    },
    "mod-crypto-native": {
        "proto": "void mod_derive(const unsigned char *, unsigned char *);",
        "call": "mod_derive(in, out);",
        "out": 16,
    },
}

_DRIVER = """#include <stdio.h>
#include <stdint.h>
{proto}
int main(void) {{
    unsigned char in[32], out[{out}];
    if (fread(in, 1, 32, stdin) != 32) return 2;
    {call}
    fwrite(out, 1, {out}, stdout);
    return 0;
}}
"""


def run_dynamic_selfcheck(task_id: str) -> int:
    """The artifact-equals-model regression (the FIX-1 bug class): the
    checker's replay face never executes native binaries, so an artifact
    that silently disagrees with its seed model would pass unnoticed.
    This face compiles the generated C for the HOST and executes it
    against the model (same source the NDK compiles; the corpus re-mints
    byte-identically, so host-compiled output proves the source). Where
    the committed .so is natively loadable (linux/arm64), the REAL
    artifact is exercised via ctypes. Structured SKIP (rc=3) when no host
    C compiler exists; the oracle stays clean-env (the anti-debug gate
    never fires outside a debugger)."""
    tdir = None
    for tier_dir in ("release",):
        candidate = ds.EVAL_ROOT / "v1" / "tasks" / tier_dir / task_id
        if (candidate / "task.yaml").is_file():
            tdir = candidate
            break
    if tdir is None:
        print(f"FAILURE code=BAD_TASK detail=unknown task {task_id!r}")
        print("VERDICT REFUSED")
        return 2
    task = ds.load_task(tdir)
    family = task["family"]
    if family not in _SELF_CHECK_SHAPES:
        print(f"SKIP dynamic-selfcheck {task_id}: family {family} has no "
              "host-executable self-check shape")
        return 3
    host_cc = shutil.which("clang") or shutil.which("cc")
    if host_cc is None:
        print("SKIP dynamic-selfcheck: no host C compiler")
        return 3
    shape = _SELF_CHECK_SHAPES[family]
    seed = FAMILY_SEEDS[family]
    gt = json.loads((tdir / task["ground_truth"]["file"])
                    .read_text(encoding="utf-8"))
    probes = gt["published_pairs"][:2]

    def model_hex(i: int, data: list[int]) -> str:
        return model_output(family, {"seed": seed}, i, data)

    matched, total = 0, 0
    native = sys.platform == "linux" and \
        platform.machine() in ("aarch64", "arm64")
    if native:
        import ctypes
        lib = ctypes.CDLL(str(tdir / task["workspace_scaffold"]["entry"]))
        fn = getattr(lib, shape["entry"])
        fn.argtypes = [ctypes.c_char_p, ctypes.c_uint,
                       ctypes.c_char_p, ctypes.c_uint]
        for p in probes:
            buf = ctypes.create_string_buffer(shape["out"])
            fn(bytes(p["input"]), 32, buf, shape["out"])
            got = buf.raw[:shape["out"]].hex()
            total += 1
            matched += int(got == model_hex(p["i"], p["input"]))
        face = "native-ctypes(committed .so)"
    else:
        cfg = derive_cfg(family, seed)
        renderer = {"arm-native-kdf": src.render_arm_c,
                    "mod-crypto-native": src.render_mod_c,
                    "smc-x86": src.render_payload_c}[family]
        text = renderer(cfg)
        if gt.get("rung") == "l2":
            # pin the SAME source semantics the L2 artifact was built from
            text = src.flatten_region(text, "rounds", "c")
        with tempfile.TemporaryDirectory(prefix="selfcheck332-") as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "target.c").write_text(text, encoding="utf-8")
            (tmp_path / "driver.c").write_text(
                _DRIVER.format(proto=shape["proto"], call=shape["call"],
                               out=shape["out"]), encoding="utf-8")
            exe = tmp_path / "selfcheck"
            proc = _run([host_cc, "-O2", "-o", str(exe),
                         str(tmp_path / "target.c"),
                         str(tmp_path / "driver.c")])
            if proc.returncode != 0:
                print(f"FAILURE code=BAD_CANDIDATE "
                      f"detail=host compile failed: {proc.stderr[-400:]}")
                print("VERDICT FAIL")
                return 1
            for p in probes:
                run = subprocess.run([str(exe)], input=bytes(p["input"]),
                                     capture_output=True, timeout=30)
                got = run.stdout[:shape["out"]].hex()
                total += 1
                matched += int(got == model_hex(p["i"], p["input"]))
        face = "host-compiled(generated source)"

    print(f"METRIC selfcheck_face={face}")
    print(f"METRIC selfcheck_matched={matched}")
    print(f"METRIC selfcheck_count={total}")
    ok = total > 0 and matched == total
    print(f"VERDICT {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


# --------------------------------------------------- flattening presence face
_FLATTEN_SHAPES = {
    "arm-native-kdf": (src.render_arm_c, "_kdf_derive"),
    "mod-crypto-native": (src.render_mod_c, "_mod_derive"),
    "smc-x86": (src.render_payload_c, "_payload_entry"),
}


def flattening_signature(family: str, rung: str) -> dict:
    """Disassembly-shape check for the L2 flattening (the robust face —
    raw .text size is noisy codegen data): compile the per-rung source to
    a host object (symbols intact), slice the entry function, and require
    the dispatcher's case compares (cmpl against state values 1 and 2) in
    L2 and their absence in L1. Host clang required (macOS/linux); the
    committed artifact stays byte-authoritative via artifact_sha256 +
    the dynamic self-check."""
    renderer, symbol = _FLATTEN_SHAPES[family]
    host_cc = shutil.which("clang") or shutil.which("cc")
    if host_cc is None:
        return {"status": "TOOLCHAIN_MISSING", "detail": "no host C compiler"}
    cfg = derive_cfg(family, FAMILY_SEEDS[family])
    text = renderer(cfg)
    if rung == "l2":
        text = src.flatten_region(text, "rounds", "c")
    with tempfile.TemporaryDirectory(prefix="flat332-") as tmp:
        obj = Path(tmp) / "target.o"
        proc = _run([host_cc, "-O2", "-c", "-"],
                    input=text) if False else None
        src_path = Path(tmp) / "target.c"
        src_path.write_text(text, encoding="utf-8")
        proc = _run([host_cc, "-O2", "-c", str(src_path), "-o", str(obj)])
        if proc.returncode != 0:
            return {"status": "FAIL", "detail": proc.stderr[-300:]}
        dis = subprocess.run(
            ["/usr/local/opt/llvm/bin/llvm-objdump", "-d", str(obj)]
            if Path("/usr/local/opt/llvm/bin/llvm-objdump").is_file()
            else (["llvm-objdump", "-d", str(obj)] if shutil.which("llvm-objdump")
                  else ["objdump", "-d", str(obj)]),
            capture_output=True, text=True).stdout
    lines = dis.splitlines()
    starts = [i for i, l in enumerate(lines) if f"<{symbol}>:" in l]
    if not starts:
        return {"status": "FAIL", "detail": f"symbol {symbol} not found"}
    body = lines[starts[0] + 1:]
    end = next((j for j, l in enumerate(body)
                if re.match(r"^[0-9a-f]+ <_?", l)), len(body))
    body = body[:end]
    # the case compares: cmpl against state values 1..n-2 (the last stage
    # compares nothing; state 0 is the entry default)
    case_vals = {int(m, 16) for l in body
                 for m in re.findall(r"cmp[l]?\t\$0x([0-9a-f]+),", l)
                 if int(m, 16) in (1, 2)}
    return {"status": "OK", "rung": rung,
            "case_cmps": sorted(case_vals)}


def run_flatten_check(task_id: str) -> int:
    task_dir = ds.EVAL_ROOT / "v1" / "tasks" / "release" / task_id
    if not (task_dir / "task.yaml").is_file():
        print(f"FAILURE code=BAD_TASK detail=unknown task {task_id!r}")
        print("VERDICT REFUSED")
        return 2
    task = ds.load_task(task_dir)
    family, rung = task["family"], json.loads(
        (task_dir / task["ground_truth"]["file"]).read_text(
            encoding="utf-8"))["rung"]
    if family not in _FLATTEN_SHAPES or rung not in ("l1", "l2"):
        print(f"SKIP flatten-check {task_id}: no flattened face")
        return 3
    sig = flattening_signature(family, rung)
    if sig["status"] != "OK":
        print(f"SKIP flatten-check {task_id}: {sig['status']} {sig.get('detail', '')}")
        return 3
    expect = {1, 2} if rung == "l2" else set()
    print(f"METRIC flatten_case_cmps={sorted(sig['case_cmps'])}")
    ok = set(sig["case_cmps"]) == expect
    print(f"VERDICT {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


# --------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="eval_native_targets.py",
        description="Mint #332 release-tier native units "
                    "(family:rung:task_id) + toolchain/proof utilities.")
    ap.add_argument("--root", default="eval/v1/tasks/release")
    ap.add_argument("--mint", action="append", default=[],
                    help="family:rung:task_id (repeatable)")
    ap.add_argument("--check-toolchain", action="store_true",
                    help="structured toolchain availability report")
    ap.add_argument("--dynamic-proof", metavar="TASK_ID", default=None,
                    help="documented local anti-debug proof (Linux x86_64 "
                         "only; structured SKIP elsewhere)")
    ap.add_argument("--self-check", metavar="TASK_ID", default=None,
                    help="artifact-equals-model dynamic regression "
                         "(host-compiled execution; native ctypes face on "
                         "linux/arm64; structured SKIP without a compiler)")
    ap.add_argument("--flatten-check", metavar="TASK_ID", default=None,
                    help="disassembly-shape check: the L2 dispatcher's case "
                         "compares must exist (and be absent at L1)")
    args = ap.parse_args(argv)
    if args.dynamic_proof:
        return run_dynamic_proof(args.dynamic_proof)
    if args.self_check:
        return run_dynamic_selfcheck(args.self_check)
    if args.flatten_check:
        return run_flatten_check(args.flatten_check)
    if args.check_toolchain:
        for row in toolchain_report(None):
            print(f"{row['toolchain']}: {row['status']} {row['path']}")
        missing = [r["toolchain"] for r in toolchain_report(None)
                   if r["status"] != "OK"]
        if missing:
            print(f"TOOLCHAIN_MISSING {','.join(missing)} "
                  "(mint degrades to a structured SKIP, never a false build)")
        return 0
    if not args.mint:
        ap.error("nothing to do: pass --mint family:rung:task_id "
                 "or --check-toolchain")
    timing: dict[str, float] = {}
    for spec in args.mint:
        family, rung, task_id = spec.split(":")
        if family not in FAMILIES:
            ap.error(f"unknown family {family!r}")
        if rung not in FAMILIES[family]["rungs"]:
            ap.error(f"family {family} has rungs "
                     f"{FAMILIES[family]['rungs']}, got {rung!r}")
        tdir = write_task_unit(family, rung, task_id, Path(args.root),
                               timing)
        print(f"MINTED {task_id} ({family} rung={rung}, "
              f"seed={FAMILY_SEEDS[family]}) -> {tdir} "
              f"[build {timing.get(task_id, 0)}s]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
