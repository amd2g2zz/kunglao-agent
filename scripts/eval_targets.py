#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_targets.py — constructed-target generator (the eval-dataset card) (smoke tier, eval-v1).

Parametric variants of known mechanism families with ground truth BY
CONSTRUCTION: one python model per family both renders the target source
and computes the reference outputs, so the captured pairs can never drift
from the artifact they were captured from (no dual maintenance, no real
workspace data — every constant is minted from a seed).

Families:
  go-arx     ~30-line SHA-1-family KDF: mutated K0 / golden constant /
             rotation base + a toy ARX step. Oracles: constant-hit
             (static: the mutated constants must appear in a candidate's
             source) + pair-match (reproduction: a re-implementation must
             reproduce the captured pairs).
  js-sign    small obfuscated-style signer bundle (hex identifiers, a
             string table, decoy constants) around two mutated 32-bit
             round constants. Oracles: constant-hit + replay-roundtrip
             through the exposed sign().
  py-derive  pure-algo 64-bit derivation (FNV-shaped with an avalanche
             fold) over three mutated 64-bit parameters. Oracle:
             replay-roundtrip on deterministic probes.

#332 release tier (eval-v1.1, WEB/NET half) — four families on a
packaging ladder (l0 readable / l1 minify+hex-ids+decoys / l2
javascript-obfuscator STRONG / l3 VM-bytecode), ALL routed through the
generator's MOD-CRYPTO core (seed-mutated SHA-256 + HMAC; stock crypto
wrong by construction) and stamped with the anti-debug surface
(debugger trap loops + timing canaries + console getter trap; trip
response = silent wrong outputs):
  web-pack-sign       sign(request) -> signature (canonical: method +
                      path + mod-sha(body) + seq), bundler-obfuscated per
                      the upgraded ladder.
  net-verify-license  challenge-response license protocol; client SDK
                      sample is JS; the checker hosts a LOOPBACK-ONLY mock
                      server (ephemeral port, no egress) and validates
                      every session server-side on published + minted
                      challenges: response = HMAC(KDF(challenge, secret),
                      canonical_payload), KDF built on mod-SHA.
  req-sign            canonical-request signing (method +
                      ordered-headers-hash + body-sha + path; HMAC over
                      mod-SHA); l2 sorts header names (order-insensitive).
  mod-crypto-js       the mod-crypto core itself as the family face — the
                      named anti-standard regression: a stock HMAC-SHA256
                      candidate fails every pair by construction.

Anti-memorization: variants differ by mutated constants (an answer
memorized from the canonical family members — stock SHA-1/SHA-256
constants, stock FNV primes — is wrong by construction; the checker-minted
probes defeat digest-table copying on the replay faces).

The minted task unit is the eval-task schema instantiated:
task.yaml + target/ + ground_truth.json + a checker.py shim that makes the
unit standalone-runnable (the bare-LLM control arm's entry surface).

CLI (regeneration / eval churn; the landed corpora were minted with
exactly these seeds):
  python scripts/eval_targets.py --root eval/v1/tasks/smoke \
      --mint go-arx:29901:go-arx-v1 --mint js-sign:29902:js-sign-v1 \
      --mint py-derive:29903:py-derive-v1
  python scripts/eval_targets.py --root eval/v1/tasks/release \
      --mint web-pack-sign:33210:web-pack-sign-l0-v1:l0 ... (rung-suffixed)

stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yaml

# canonical family members a lazy/memorizing candidate would reach for —
# the generator REFUSES to mint them (divergence is the anti-memorization
# property, asserted per variant at mint time)
CANONICAL_K0 = 0x5A827999
CANONICAL_GOLDEN = 0x9E3779B9

M32 = 0xFFFFFFFF
M64 = 0xFFFFFFFFFFFFFFFF

SCHEMA_TASK = "kunglao-eval-task/1"
SCHEMA_GROUND_TRUTH = "kunglao-eval-ground-truth/1"

# family registry: toolchain (checker replay face), target filename,
# candidate contract anchor
FAMILIES: dict[str, dict] = {
    "go-arx": {
        "toolchain": "go",
        "target": "target/sample_kdf.go",
        "language": "go",
        "task_id": "go-arx-v1",
        "seed": 29901,
        "space_bits": 96,
        "kind": "pair-match",
        "oracles": ["constant-hit", "pair-match"],
        "thresholds": {"min_constant_hits": 3, "min_pair_ratio": 0.75},
    },
    "js-sign": {
        "toolchain": "node",
        "target": "target/sign_bundle.js",
        "language": "javascript",
        "task_id": "js-sign-v1",
        "seed": 29902,
        "space_bits": 64,
        "kind": "replay-roundtrip",
        "oracles": ["constant-hit", "replay-roundtrip"],
        "thresholds": {"min_constant_hits": 2, "min_pair_ratio": 1.0},
    },
    "py-derive": {
        "toolchain": "python3",
        "target": "target/derive.py",
        "language": "python",
        "task_id": "py-derive-v1",
        "seed": 29903,
        "space_bits": 192,
        "kind": "replay-roundtrip",
        "oracles": ["replay-roundtrip"],
        "thresholds": {"min_pair_ratio": 1.0},
    },
    # ---- #332 release tier (eval-v1.1, WEB/NET half) --------------------
    # every family routes its derivation core through the mod-crypto
    # generator (seed-mutated SHA-256/HMAC below) — stock-crypto candidates
    # fail by construction (the named anti-standard regression).
    "web-pack-sign": {
        "toolchain": "node",
        "target": "target/web_sign_bundle.js",
        "language": "javascript",
        "tier": "release",
        "space_bits": 256,
        "kind": "replay-roundtrip",
        "anchor_fn": "sign",
        "rungs": ("l0", "l1", "l2", "l3"),
    },
    "net-verify-license": {
        "toolchain": "node",
        "target": "target/license_client.js",
        "language": "javascript",
        "tier": "release",
        "space_bits": 256,
        "kind": "replay-roundtrip",
        "anchor_fn": "handshake",
        "rungs": ("l1", "l2"),
    },
    "req-sign": {
        "toolchain": "node",
        "target": "target/request_signer.js",
        "language": "javascript",
        "tier": "release",
        "space_bits": 256,
        "kind": "replay-roundtrip",
        "anchor_fn": "signRequest",
        "rungs": ("l1", "l2"),
    },
    "mod-crypto-js": {
        "toolchain": "node",
        "target": "target/modcrypto_bundle.js",
        "language": "javascript",
        "tier": "release",
        "space_bits": 256,
        "kind": "replay-roundtrip",
        "anchor_fn": "sign",
        "rungs": ("l1", "l2", "l3"),
    },
}

# packaging ladder per release unit (obfuscation level; the derivation core
# is INVARIANT across rungs of one seed — only the wrapping changes)
RUNG_ORACLES = {
    "l0": ["constant-hit", "replay-roundtrip"],
    "l1": ["constant-hit", "replay-roundtrip"],
    "l2": ["replay-roundtrip"],  # rc4 stringArray buries literals: honest
    "l3": ["replay-roundtrip"],  # VM bytecode buries everything: behavior only
}
RUNG_THRESHOLDS = {
    "l0": {"min_constant_hits": 1, "min_pair_ratio": 1.0},
    "l1": {"min_constant_hits": 1, "min_pair_ratio": 1.0},
    "l2": {"min_pair_ratio": 1.0},
    "l3": {"min_pair_ratio": 1.0},
}

# owner addition B: anti-debug surface stamped into every JS artifact
ANTI_DEBUG_TRAPS = ["debugger-loop", "timing", "console-getter"]
ANTI_DEBUG_NOTE = ("silent in a clean node env (no devtools): traps never "
                   "fire and outputs are deterministic; on a trip the "
                   "response is SILENT WRONG OUTPUT, never an exception or "
                   "log line")


# ------------------------------------------------------------ deterministic rng
def _splitmix32(x: int) -> int:
    """SplitMix32 finalizer — a pure function, so every derived constant is
    stable across python versions and machines (no RNG module state)."""
    x = (x + 0x9E3779B9) & M32
    z = x
    z = ((z ^ (z >> 16)) * 0x21F0AAAD) & M32
    z = ((z ^ (z >> 15)) * 0x735A2D97) & M32
    return (z ^ (z >> 15)) & M32


def _u32(seed: int, lane: int) -> int:
    v = _splitmix32((seed ^ (lane * 0x85EBCA6B)) & M32) | 1  # odd, nonzero
    return v & M32


def _u64(seed: int, lane: int) -> int:
    return ((_u32(seed, lane) << 32) | _u32(seed ^ 0xDEADBEEF, lane)) & M64


# ------------------------------------------------------------------ configs
def derive_cfg(family: str, seed: int, rung: str = "l1") -> dict:
    """The per-variant constant set (the ground truth by construction).

    Release families take ``rung`` because the packaging ladder changes
    the CANONICALIZATION (req-sign sorts header names at l2+) — the
    derivation core (mod-SHA + key) is invariant per seed across rungs.
    """
    if family == "go-arx":
        k0, z, rot_base = _u32(seed, 1), _u32(seed, 2), _u32(seed, 3)
        # refuse the canonical SHA-1-family members: memorizing the stock
        # constants must score zero, so the variant must not be one
        while k0 == CANONICAL_K0:
            k0 = _u32(k0, 1)
        while z == CANONICAL_GOLDEN:
            z = _u32(z, 2)
        return {"k0": k0, "z": z, "rot_base": rot_base}
    if family == "js-sign":
        c1, c2 = _u32(seed, 1), _u32(seed, 2)
        d1, d2 = _u32(seed, 3), _u32(seed, 4)
        while d1 in (c1, c2):
            d1 = _u32(d1, 3)
        while d2 in (c1, c2, d1):
            d2 = _u32(d2, 4)
        return {"c1": c1, "c2": c2, "decoys": [d1, d2]}
    if family == "py-derive":
        return {"offset": _u64(seed, 1), "prime": _u64(seed, 2),
                "fold": _u64(seed, 3)}
    if family == "web-pack-sign":
        cfg = _mod_key_cfg(seed)
        cfg["sort_headers"] = False
        return cfg
    if family == "req-sign":
        cfg = _mod_key_cfg(seed)
        cfg["sort_headers"] = rung in ("l2", "l3")
        return cfg
    if family == "net-verify-license":
        cfg = _mod_key_cfg(seed)
        cfg["device"] = f"{_u32(seed, 61):06x}{_u32(seed, 62):06x}"[:12]
        cfg["rounds"] = 2 + (seed % 2)
        return cfg
    if family == "mod-crypto-js":
        cfg = _mod_key_cfg(seed)
        return cfg
    raise ValueError(f"unknown family: {family}; valid: {sorted(FAMILIES)}")


# ------------------------------------------------------------- mod-crypto core
# The generator's OWN cipher face (owner addition A): a seed-mutated
# SHA-256 — identical schedule, mutated initial hash + round constants —
# plus RFC 2104 HMAC over it. Stock-lib candidates fail by construction
# (the named anti-standard regression: a memorized stdlib HMAC-SHA256
# NEVER reproduces a mod-crypto pair).
STOCK_SHA256_H = (0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A,
                  0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19)
STOCK_SHA256_K = (
    0x428A2F98, 0x71374491, 0xB5C0FBCF, 0xE9B5DBA5, 0x3956C25B, 0x59F111F1,
    0x923F82A4, 0xAB1C5ED5, 0xD807AA98, 0x12835B01, 0x243185BE, 0x550C7DC3,
    0x72BE5D74, 0x80DEB1FE, 0x9BDC06A7, 0xC19BF174, 0xE49B69C1, 0xEFBE4786,
    0x0FC19DC6, 0x240CA1CC, 0x2DE92C6F, 0x4A7484AA, 0x5CB0A9DC, 0x76F988DA,
    0x983E5152, 0xA831C66D, 0xB00327C8, 0xBF597FC7, 0xC6E00BF3, 0xD5A79147,
    0x06CA6351, 0x14292967, 0x27B70A85, 0x2E1B2138, 0x4D2C6DFC, 0x53380D13,
    0x650A7354, 0x766A0ABB, 0x81C2C92E, 0x92722C85, 0xA2BFE8A1, 0xA81A664B,
    0xC24B8B70, 0xC76C51A3, 0xD192E819, 0xD6990624, 0xF40E3585, 0x106AA070,
    0x19A4C116, 0x1E376C08, 0x2748774C, 0x34B0BCB5, 0x391C0CB3, 0x4ED8AA4A,
    0x5B9CCA4F, 0x682E6FF3, 0x748F82EE, 0x78A5636F, 0x84C87814, 0x8CC70208,
    0x90BEFFFA, 0xA4506CEB, 0xBEF9A3F7, 0xC67178F2)


def mod_sha_cfg(seed: int) -> dict:
    """Seed-mutated SHA-256 constants: 8 initial hash words + the 64-word
    round table, every word repaired away from its stock value (>= 7/8 H
    and >= 60/64 K differ from stock by construction)."""
    h = [_u32(seed, 10 + i) for i in range(8)]
    k = [_u32(seed ^ 0x5EEDC0DE, 40 + j) for j in range(64)]
    for i in range(8):
        while h[i] == STOCK_SHA256_H[i]:
            h[i] = _u32(h[i], 10 + i)
    for j in range(64):
        while k[j] == STOCK_SHA256_K[j]:
            k[j] = _u32(k[j], 40 + j)
    return {"h": h, "k": k}


def _sha_rotr(x: int, n: int) -> int:
    return ((x >> n) | (x << (32 - n))) & M32


def _sha_pad(data: bytes) -> bytes:
    msg = bytearray(data)
    ml = len(data) * 8
    msg.append(0x80)
    while len(msg) % 64 != 56:
        msg.append(0)
    msg += ml.to_bytes(8, "big")
    return bytes(msg)


def mod_sha256(cfg: dict, data: bytes) -> bytes:
    """SHA-256 with the mutated H/K tables (pure python reference for the
    generator's mod-crypto core; multi-block + padding standard)."""
    h = list(cfg["h"])
    kt = cfg["k"]
    msg = _sha_pad(data)
    for off in range(0, len(msg), 64):
        w = [int.from_bytes(msg[off + i * 4: off + i * 4 + 4], "big")
             for i in range(16)]
        for i in range(16, 64):
            s0 = (_sha_rotr(w[i - 15], 7) ^ _sha_rotr(w[i - 15], 18)
                  ^ (w[i - 15] >> 3))
            s1 = (_sha_rotr(w[i - 2], 17) ^ _sha_rotr(w[i - 2], 19)
                  ^ (w[i - 2] >> 10))
            w.append((w[i - 16] + s0 + w[i - 7] + s1) & M32)
        a, b, c, d, e, f, g, hh = h
        for i in range(64):
            s1 = _sha_rotr(e, 6) ^ _sha_rotr(e, 11) ^ _sha_rotr(e, 25)
            ch = (e & f) ^ (~e & g)
            t1 = (hh + s1 + ch + kt[i] + w[i]) & M32
            s0 = _sha_rotr(a, 2) ^ _sha_rotr(a, 13) ^ _sha_rotr(a, 22)
            maj = (a & b) ^ (a & c)
            t2 = (s0 + maj) & M32
            hh, g, f = g, f, e
            e = (d + t1) & M32
            d, c, b = c, b, a
            a = (t1 + t2) & M32
        h = [(x + y) & M32
             for x, y in zip(h, (a, b, c, d, e, f, g, hh))]
    return b"".join(x.to_bytes(4, "big") for x in h)


def mod_hmac(cfg: dict, key: bytes, msg: bytes) -> bytes:
    """RFC 2104 HMAC over the mutated core (block size 64)."""
    block = 64
    k = key if len(key) <= block else mod_sha256(cfg, key)
    k = k + b"\x00" * (block - len(k))
    ipad = bytes(b ^ 0x36 for b in k)
    opad = bytes(b ^ 0x5C for b in k)
    return mod_sha256(cfg, opad + mod_sha256(cfg, ipad + msg))


def _mod_key_cfg(seed: int) -> dict:
    """The shared release-family base: mutated core + a seeded 32-byte key
    + a seeded separator code point (kept in the ASCII control range so it
    can never appear inside method/path/header payloads)."""
    cfg = mod_sha_cfg(seed)
    key = b"".join(_u32(seed, 21 + i).to_bytes(4, "big") for i in range(8))
    cfg["key_hex"] = key.hex()
    cfg["sep_code"] = 0x1F + (_u32(seed, 30) % 8)
    return cfg


def license_session_key(cfg: dict, challenge_hex: str) -> bytes:
    """KDF(challenge, secret): mod-SHA chained over (secret || challenge),
    ``rounds`` folds — the KDF is built on the mod-crypto generator, never
    on a stock primitive."""
    secret = bytes.fromhex(cfg["key_hex"])
    k = mod_sha256(cfg, secret + bytes.fromhex(challenge_hex))
    for _ in range(int(cfg.get("rounds", 2)) - 1):
        k = mod_sha256(cfg, k)
    return k


def license_response(cfg: dict, challenge_hex: str, client_nonce: str,
                     device: str, i: int) -> str:
    """response = HMAC(KDF(challenge, secret), canonical_payload)."""
    sep = chr(cfg["sep_code"])
    canonical = sep.join([challenge_hex, client_nonce, device, str(i)])
    return mod_hmac(cfg, license_session_key(cfg, challenge_hex),
                    canonical.encode("latin1")).hex()


def _rotl32(x: int, r: int) -> int:
    r %= 32
    return ((x << r) | (x >> (32 - r))) & M32 if r else x & M32


# ------------------------------------------------------------------- models
# ONE python model per family: the same function computes the reference
# outputs (ground truth) and documents the transform the renderer emits —
# construction, not capture.
def go_model(cfg: dict, i: int, x: int) -> int:
    t = ((i + 1) * cfg["rot_base"]) & M32
    r = (i % 31) + 1
    return ((x + _rotl32(t, r) + cfg["z"]) & M32) ^ cfg["k0"]


def js_model(cfg: dict, data: bytes) -> str:
    h = cfg["c1"]
    for b in data:
        h = (h ^ b) & M32
        h = _rotl32(h, 5)
        h = (h + cfg["c2"]) & M32
    h = (h ^ (h >> 16)) & M32
    return f"{h:08x}"


def py_model(cfg: dict, data: bytes) -> int:
    h = cfg["offset"]
    for b in data:
        h = ((h ^ b) * cfg["prime"]) & M64
    h ^= h >> 31
    h = (h * cfg["fold"]) & M64
    h ^= h >> 29
    return h


def _web_canonical(cfg: dict, request: dict) -> str:
    """web-pack-sign canonical: method + path + body-sha + seq over the
    mod core (body digest is MUTATED sha — a stock sha256 body digest
    makes the whole signature wrong: the anti-standard regression)."""
    sep = chr(cfg["sep_code"])
    body_sha = mod_sha256(cfg, str(request["body"]).encode("latin1")).hex()
    return sep.join([str(request["method"]), str(request["path"]),
                     body_sha, str(request["seq"])])


def _headers_hash(cfg: dict, headers) -> str:
    sep = chr(cfg["sep_code"])
    pairs = [list(p) for p in headers]
    if cfg.get("sort_headers"):
        pairs = sorted(pairs, key=lambda p: str(p[0]))
    blob = sep.join(f"{k}:{v}" for k, v in pairs)
    return mod_sha256(cfg, blob.encode("latin1")).hex()


def _req_canonical(cfg: dict, request: dict) -> str:
    """req-sign canonical (card order): method + ordered-headers-hash +
    body-sha + path. At l1 the GIVEN header order is canonical; at l2+
    header names are sorted (same request, permuted order -> same
    signature: the ordering subtlety the naive signer misses)."""
    sep = chr(cfg["sep_code"])
    hh = _headers_hash(cfg, request.get("headers", []))
    body_sha = mod_sha256(cfg, str(request["body"]).encode("latin1")).hex()
    return sep.join([str(request["method"]), hh, body_sha, str(request["path"])])


def model_output(family: str, cfg: dict, i: int, x):
    if family == "go-arx":
        xin = x[0] if isinstance(x, list) else x  # pairs store input as [x]
        return go_model(cfg, i, xin)
    if family == "js-sign":
        return js_model(cfg, bytes(x))
    if family == "py-derive":
        return py_model(cfg, bytes(x))
    if family == "web-pack-sign":
        return mod_hmac(cfg, bytes.fromhex(cfg["key_hex"]),
                        _web_canonical(cfg, x).encode("latin1")).hex()
    if family == "req-sign":
        return mod_hmac(cfg, bytes.fromhex(cfg["key_hex"]),
                        _req_canonical(cfg, x).encode("latin1")).hex()
    if family == "mod-crypto-js":
        return mod_hmac(cfg, bytes.fromhex(cfg["key_hex"]), bytes(x)).hex()
    raise ValueError(f"unknown family: {family}")


# model-side cfg for the checker: ground truth carries the PUBLIC constants
# on `constants` (the static face) and the FULL mutated core on `core`
# (the replay model); release families need the latter.
def model_cfg(gt: dict) -> dict:
    return gt.get("core") or gt["constants"]


# -------------------------------------------------------------- probe minting
GO_INPUT_FORMULA = "params[i] = uint32(i)*2654435761 + 1"


def go_inputs(count: int) -> list[int]:
    return [(i * 2654435761 + 1) & M32 for i in range(count)]


def _request_probe(family: str, seed: int, k: int) -> dict:
    """One seeded request (web-pack-sign / req-sign shape). Deterministic
    per (seed, k) — the checker recomputes, stores nothing."""
    methods = ("POST", "GET", "PUT", "DELETE")
    path = f"/v1/{_u32(seed ^ 0x5EED, k + 1):08x}/{k}"
    body = (f"{_u32(seed, 70 + (k % 8)):08x}"
            f"{_u32(seed ^ 0xB0D, 70 + (k % 8)):08x}"
            f"{_u32(seed ^ 0xF00D, 70 + (k % 8)):08x}")
    req = {"method": methods[k % len(methods)], "path": path, "body": body,
           "seq": k}
    if family == "req-sign":
        names = ("x-canary", "accept", "x-trace", "content-digest")
        order = _u32(seed ^ 0x51CE, 80 + (k % 8)) % 4
        picked = [(names[(order + j) % 4], f"v{(order + j) % 9}")
                  for j in range(3)]
        req["headers"] = [list(p) for p in picked]
    return req


def _license_probe(seed: int, k: int) -> dict:
    """One seeded challenge record (net-verify-license): the server mints
    the challenge, the client answers with HMAC(KDF(challenge, secret),
    canonical_payload)."""
    ch = f"{_u32(seed ^ 0xCA11, 50 + k):08x}{_u32(seed ^ 0xCA11, 60 + k):08x}"
    nonce = f"{_u32(seed ^ 0x10CE, 55 + k):08x}"
    return {"challenge": ch, "client_nonce": nonce}


def minted_probes(family: str, seed: int, count: int) -> list[dict]:
    """Checker-minted probes: fresh inputs derived from the variant seed —
    the anti-digest-table face (a candidate hardcoding the PUBLISHED
    pairs passes those and fails these, by construction). Inputs are
    stored nowhere; the checker recomputes them (and the expected
    outputs) from the seed model at run time."""
    probes = []
    for k in range(count):
        if family == "go-arx":
            data = [_u32(seed ^ 0x5EED, k + 1)]  # one uint32 per probe
        elif family in ("web-pack-sign", "req-sign"):
            probes.append({"i": 100 + k, "request": _request_probe(
                family, seed ^ 0x5EED, 100 + k)})
            continue
        elif family == "net-verify-license":
            p = _license_probe(seed ^ 0x5EED, 100 + k)
            probes.append({"i": 100 + k, "challenge": p["challenge"],
                           "client_nonce": p["client_nonce"]})
            continue
        else:
            raw = _u64(seed ^ 0x5EED, k + 1).to_bytes(8, "big")
            if family == "js-sign":
                data = list(raw[:6])  # 6-byte inputs (byte-level sign)
            else:
                data = list(raw)  # py face: the full 8 bytes
        probes.append({"i": 100 + k, "input": data})
    return probes


def published_pairs(family: str, cfg: dict, count: int) -> list[dict]:
    if family == "go-arx":
        return [{"i": i, "input": [x], "out": go_model(cfg, i, x)}
                for i, x in enumerate(go_inputs(count))]
    if family in ("web-pack-sign", "req-sign"):
        return [{"i": k, "request": _request_probe(family, 0, k),
                 "out": model_output(family, cfg, k,
                                     _request_probe(family, 0, k))}
                for k in range(count)]
    if family == "net-verify-license":
        pairs = []
        for k in range(count):
            p = _license_probe(0, k)
            out = license_response(cfg, p["challenge"], p["client_nonce"],
                                   cfg["device"], k)
            pairs.append({"i": k, "challenge": p["challenge"],
                          "client_nonce": p["client_nonce"], "out": out})
        return pairs
    fn = js_model if family == "js-sign" else py_model
    fixed = minted_probes(family, 0, count)  # published face: stable inputs
    # published pairs take i = 0..N-1; checker-minted probes take i >= 100
    # (disjoint keys — the keyed comparison never aliases the two faces)
    if family == "mod-crypto-js":
        return [{"i": k, "input": p["input"],
                 "out": model_output(family, cfg, k, p["input"])}
                for k, p in enumerate(fixed)]
    return [{"i": k, "input": p["input"], "out": fn(cfg, bytes(p["input"]))}
            for k, p in enumerate(fixed)]


# ------------------------------------------------------------------ renderers
def render_go(cfg: dict) -> str:
    return f'''// sample_kdf.go — CONSTRUCTED eval target (family go-arx, eval-v1).
// NOT malware; no real workspace data: every constant below is a seeded
// mutation of the SHA-1-family mechanism shape, minted by eval_targets.py.
//
// Recover the three embedded constants and re-implement the pipeline:
//   out = ((in + rotl32((i+1)*rotBase, (i%31)+1) + z) mod 2^32) XOR k0
// The published capture pins the fixed face
//   {GO_INPUT_FORMULA}
// but the program is INPUT-AGNOSTIC: it reads one JSON object per line on
// stdin ({{"i": N, "in": X}}) and prints one per line
// ({{"i": N, "in": X, "out": Y}}) — the checker drives freshly minted
// inputs through it, so a PASS requires the actual derivation (a
// constants+lookup shortcut fails on inputs it never saw).
package main

import (
\t"bufio"
\t"encoding/json"
\t"fmt"
\t"os"
)

const (
\tk0      uint32 = 0x{cfg["k0"]:08x}
\tz       uint32 = 0x{cfg["z"]:08x}
\trotBase uint32 = 0x{cfg["rot_base"]:08x}
)

func rotl32(x uint32, r uint) uint32 {{
\treturn (x << r) | (x >> (32 - r))
}}

func arxStep(x, t uint32, i uint) uint32 {{
\treturn ((x + rotl32(t, (i%31)+1) + z) & 0xffffffff) ^ k0
}}

func main() {{
\tsc := bufio.NewScanner(os.Stdin)
\tsc.Buffer(make([]byte, 64*1024), 1024*1024)
\tw := bufio.NewWriter(os.Stdout)
\tdefer w.Flush()
\tfor sc.Scan() {{
\t\tvar req struct {{
\t\t\tI  int    `json:"i"`
\t\t\tIn uint32 `json:"in"`
\t\t}}
\t\tif err := json.Unmarshal(sc.Bytes(), &req); err != nil {{
\t\t\tcontinue
\t\t}}
\t\tout := arxStep(req.In, (uint32(req.I)+1)*rotBase, uint(req.I))
\t\tfmt.Fprintf(w, "{{\\"i\\": %d, \\"in\\": %d, \\"out\\": %d}}\\n",
\t\t\treq.I, req.In, out)
\t}}
}}
'''


def render_js(cfg: dict) -> str:
    d1, d2 = cfg["decoys"]
    return f'''// sign_bundle.js — #299 CONSTRUCTED eval target (family js-sign, eval-v1).
// NOT malware; no real workspace data: an obfuscated-style signer bundle
// seeded by eval_targets.py. Two of the four 32-bit constants below are
// load-bearing (C1, C2); the D-constants are decoys.
// Contract: module.exports.sign(inputString) -> 8-hex-char lowercase.
var _0x4b = ['round', 'fold'];
var C1 = 0x{cfg["c1"]:08x};
var C2 = 0x{cfg["c2"]:08x};
var D1 = 0x{d1:08x};
var D2 = 0x{d2:08x};

function _0x2f(h, b) {{
  h = (h ^ b) >>> 0;
  h = ((h << 5) | (h >>> 27)) >>> 0;
  return (h + C2) >>> 0;
}}

function _0x7a(h) {{
  return (((h ^ (h >>> 16)) >>> 0) + D2 * 0) >>> 0;
}}

function sign(input) {{
  var h = C1;
  for (var i = 0; i < input.length; i++) {{
    h = _0x2f(h, input.charCodeAt(i) & 0xff);
  }}
  h = _0x7a(h);
  return ('00000000' + h.toString(16)).slice(-8);
}}

module.exports = {{ sign: sign, _table: _0x4b }};

if (typeof require !== 'undefined' && require.main === module) {{
  console.log(JSON.stringify({{ in: 'alpha', out: sign('alpha') }}));
  console.log(JSON.stringify({{ in: 'bravo', out: sign('bravo') }}));
}}
'''


def render_py(cfg: dict) -> str:
    return f'''# derive.py — #299 CONSTRUCTED eval target (family py-derive, eval-v1).
# NOT malware; no real workspace data: a pure-algo 64-bit derivation seeded
# by eval_targets.py. Recover the three parameters and re-implement
# derive(data: bytes) -> int so it reproduces the reference outputs.
OFFSET = 0x{cfg["offset"]:016x}
PRIME = 0x{cfg["prime"]:016x}
FOLD = 0x{cfg["fold"]:016x}

_M64 = (1 << 64) - 1


def derive(data: bytes) -> int:
    h = OFFSET
    for b in data:
        h = ((h ^ b) * PRIME) & _M64
    h ^= h >> 31
    h = (h * FOLD) & _M64
    h ^= h >> 29
    return h


if __name__ == "__main__":
    for probe in (b"alpha", b"bravo"):
        print(probe.hex(), derive(probe))
'''


# ===========================================================================
#                     #332 release-tier renderers (WEB/NET)
# ===========================================================================
# One readable JS template per artifact with two swappable digest cores:
#   l0/l1  readable compression loop (l1 additionally gets the deterministic
#          minify+hex-ids+decoys transform below);
#   l2     the l0 source shipped through javascript-obfuscator@5.8.0 STRONG
#          preset at MINT time (npx; see write_task_unit) — packaging only,
#          never re-minted byte-identically (selfDefending/stringArray
#          rotation are randomized: documented, behavior-verified);
#   l3     a seed-mutated stack-VM: the compression function compiled to a
#          custom opcode program (python transform below) + a JS interpreter
#          loop.
# The derivation core is INVARIANT across rungs of one seed, so every rung
# of a family reproduces the same ground-truth pairs.

_VM_OPS = ("load", "store", "push", "add", "xor", "and", "not", "rotr",
           "shr", "dup")


def _vm_opcode_table(seed: int) -> dict[str, int]:
    """Seeded permutation: op name -> emitted opcode number (the seed
    mutation of the custom bytecode)."""
    nums = list(range(len(_VM_OPS)))
    for i in range(len(nums) - 1, 0, -1):
        j = _u32(seed, 200 + i) % (i + 1)
        nums[i], nums[j] = nums[j], nums[i]
    return dict(zip(_VM_OPS, nums))


def _vm_compile_sha(cfg: dict, seed: int) -> list[int]:
    """Compile ONE mod-SHA256 compression pass to the custom opcode stream.

    Memory layout: mem[0..7] working vars (carry in), mem[8..23] the 16
    block words, mem[24..71] the extended schedule, mem[72]/[73] t1/t2.
    The wrapper initializes mem[0..7] with the carry per block and folds
    mem[0..7] back after the run (chaining lives in the wrapper, both in
    the python verifier and the rendered JS interpreter client).
    """
    op = _vm_opcode_table(seed ^ 0x7A33)
    prog: list[int] = []

    def e(name: str, arg=None) -> None:
        prog.append(op[name])
        if arg is not None:
            prog.append(int(arg) & M32)

    kt = cfg["k"]
    for i in range(16, 64):
        # w[i] = (w[i-16] + s0 + w[i-7] + s1) mod 2^32
        e("load", 8 + i - 16)
        e("load", 8 + i - 15); e("rotr", 7)
        e("load", 8 + i - 15); e("rotr", 18); e("xor")
        e("load", 8 + i - 15); e("shr", 3); e("xor")
        e("add")
        e("load", 8 + i - 7); e("add")
        e("load", 8 + i - 2); e("rotr", 17)
        e("load", 8 + i - 2); e("rotr", 19); e("xor")
        e("load", 8 + i - 2); e("shr", 10); e("xor")
        e("add")
        e("store", 8 + i)
    for i in range(64):
        # t1 = h + S1(e) + Ch(e,f,g) + K[i] + w[i]
        e("load", 4); e("rotr", 6)
        e("load", 4); e("rotr", 11); e("xor")
        e("load", 4); e("rotr", 25); e("xor")
        e("load", 4); e("load", 5); e("and")
        e("load", 4); e("not"); e("load", 6); e("and"); e("xor")
        e("add")                      # S1 + Ch
        e("load", 7); e("add")        # + h
        e("push", kt[i]); e("add")    # + K[i] (seed-mutated immediate)
        e("load", 8 + i); e("add")    # + w[i]
        e("store", 72)                # t1
        # t2 = S0(a) + Maj(a,b,c)
        e("load", 0); e("rotr", 2)
        e("load", 0); e("rotr", 13); e("xor")
        e("load", 0); e("rotr", 22); e("xor")
        e("load", 0); e("load", 1); e("and")
        e("load", 0); e("load", 2); e("and"); e("xor")
        e("add")
        e("store", 73)
        # working-var rotation
        e("load", 6); e("store", 7)
        e("load", 5); e("store", 6)
        e("load", 4); e("store", 5)
        e("load", 3); e("load", 72); e("add"); e("store", 4)
        e("load", 2); e("store", 3)
        e("load", 1); e("store", 2)
        e("load", 0); e("store", 1)
        e("load", 73); e("load", 72); e("add"); e("store", 0)
    return prog


def _vm_step(prog: list[int], op: dict[str, int], mem: list[int]) -> None:
    """Python mirror of the rendered JS interpreter (mint-time proof the
    bytecode equals the model — every artifact build re-verifies)."""
    inv = {v: k for k, v in op.items()}
    st: list[int] = []
    pc = 0
    while pc < len(prog):
        name = inv[prog[pc]]
        pc += 1
        if name == "load":
            addr = prog[pc]; pc += 1
            st.append(mem[addr] & M32)
        elif name == "store":
            addr = prog[pc]; pc += 1
            mem[addr] = st.pop() & M32
        elif name == "push":
            v = prog[pc]; pc += 1
            st.append(v & M32)
        elif name == "rotr":
            n = prog[pc]; pc += 1
            st.append(_sha_rotr(st.pop(), n))
        elif name == "shr":
            n = prog[pc]; pc += 1
            st.append((st.pop() >> n) & M32)
        elif name == "add":
            b = st.pop(); a = st.pop(); st.append((a + b) & M32)
        elif name == "xor":
            b = st.pop(); a = st.pop(); st.append((a ^ b) & M32)
        elif name == "and":
            b = st.pop(); a = st.pop(); st.append((a & b) & M32)
        elif name == "not":
            st.append(~st.pop() & M32)
        elif name == "dup":
            st.append(st[-1])
        else:  # pragma: no cover - inv is closed over _VM_OPS
            raise ValueError(f"unknown opcode {name}")


def _vm_sha256(cfg: dict, seed: int, data: bytes) -> bytes:
    """Run the compiled program over the padded blocks (verifier)."""
    op = _vm_opcode_table(seed ^ 0x7A33)
    msg = _sha_pad(data)
    carry = list(cfg["h"])
    for off in range(0, len(msg), 64):
        mem = [0] * 80
        for i in range(16):
            mem[8 + i] = int.from_bytes(msg[off + i * 4: off + i * 4 + 4],
                                        "big")
        for j in range(8):
            mem[j] = carry[j]
        _vm_step(_vm_compile_sha(cfg, seed), op, mem)
        carry = [(carry[j] + mem[j]) & M32 for j in range(8)]
    return b"".join(x.to_bytes(4, "big") for x in carry)


def _vm_self_test(cfg: dict, seed: int) -> None:
    """Named construction guard: the VM bytecode MUST equal the model on
    every mint (a drift here would mint a lying artifact)."""
    for data in (b"", b"abc", b"x" * 55, b"y" * 56, b"z" * 119, b"q" * 128):
        want = mod_sha256(cfg, data)
        got = _vm_sha256(cfg, seed, data)
        assert got == want, f"vm bytecode drift on {data[:8]!r}..."


def _render_vm_js(cfg: dict, seed: int) -> str:
    """The JS face of the VM rung: program literal + interpreter loop +
    the digest wrapper (carry chaining outside the bytecode)."""
    op = _vm_opcode_table(seed ^ 0x7A33)
    prog = _vm_compile_sha(cfg, seed)
    cases = "\n".join([
        f"      case {op['load']}: st.push(mem[P[pc++]] >>> 0); break;",
        f"      case {op['store']}: mem[P[pc++]] = st.pop() >>> 0; break;",
        f"      case {op['push']}: st.push(P[pc++] >>> 0); break;",
        f"      case {op['add']}: {{ var b = st.pop(); var a = st.pop();"
        f" st.push((a + b) >>> 0); break; }}",
        f"      case {op['xor']}: {{ var b = st.pop(); var a = st.pop();"
        f" st.push((a ^ b) >>> 0); break; }}",
        f"      case {op['and']}: {{ var b = st.pop(); var a = st.pop();"
        f" st.push((a & b) >>> 0); break; }}",
        f"      case {op['not']}: st.push(~st.pop() >>> 0); break;",
        f"      case {op['rotr']}: {{ var n = P[pc++]; var x = st.pop();"
        f" st.push(((x >>> n) | (x << (32 - n))) >>> 0); break; }}",
        f"      case {op['shr']}: {{ var n = P[pc++];"
        f" st.push(st.pop() >>> n); break; }}",
        f"      case {op['dup']}: st.push(st[st.length - 1]); break;",
    ])
    prog_text = ",".join(str(v) for v in prog)
    return (
        "var _P = [" + prog_text + "];\n"
        "function _vmRun(P, mem) {\n"
        "  var st = [];\n"
        "  var pc = 0;\n"
        "  while (pc < P.length) {\n"
        "    switch (P[pc++]) {\n"
        + cases + "\n"
        "      default: return;\n"
        "    }\n"
        "  }\n"
        "}\n"
        "function _newMem() {\n"
        "  var m = [];\n"
        "  for (var i = 0; i < 80; i++) m.push(0);\n"
        "  return m;\n"
        "}\n"
        "function _loadBlock(mem, b, off) {\n"
        "  for (var i = 0; i < 16; i++) {\n"
        "    mem[8 + i] = (b[off + 4 * i] << 24 | b[off + 4 * i + 1] << 16"
        " | b[off + 4 * i + 2] << 8 | b[off + 4 * i + 3]) >>> 0;\n"
        "  }\n"
        "}\n"
        "function _digest(msgBytes) {\n"
        "  var padded = _pad(msgBytes);\n"
        "  var carry = HT.slice();\n"
        "  var mem = _newMem();\n"
        "  for (var off = 0; off < padded.length; off += 64) {\n"
        "    _loadBlock(mem, padded, off);\n"
        "    for (var j = 0; j < 8; j++) mem[j] = carry[j];\n"
        "    _vmRun(_P, mem);\n"
        "    for (var j = 0; j < 8; j++) carry[j] = (carry[j] + mem[j])"
        " >>> 0;\n"
        "  }\n"
        "  return carry;\n"
        "}\n")


_JS_ANTIDEBUG_TMPL = """// anti-debug surface (owner addition):
// silent-wrong on trip, silent-clean otherwise
var AD = (function (sd) {
  var ok = true;
  function check() {
    var t0 = Date.now();
    var g = sd % 7;
    while (g-- > 0) { debugger; }
    if (Date.now() - t0 > 250) { ok = false; return; }
    try {
      if (typeof performance !== 'undefined' && performance.now) {
        var p0 = performance.now();
        var g2 = sd % 5;
        while (g2-- > 0) { debugger; }
        if (performance.now() - p0 > 250) { ok = false; return; }
      }
    } catch (e) { /* no monotonic clock: the Date canary above still holds */ }
    try {
      Object.defineProperty(console, '_kx', {
        get: function () { ok = false; return 0; }, configurable: true });
    } catch (e) { /* frozen console: getter trap unavailable */ }
  }
  check();
  return { ok: function () { return ok; } };
})(__AD_SEED__);
"""

_JS_CONST_TMPL = """var KX = '{key_hex}';
var KT = [{k_table}];
var HT = [{h_table}];
var SEPCH = String.fromCharCode(0x{sep:02x});
"""

_JS_HELPERS_TMPL = """function _bytesOf(s) {
  var o = [];
  for (var i = 0; i < s.length; i++) o.push(s.charCodeAt(i) & 0xff);
  return o;
}
function _unhex(h) {
  var o = [];
  for (var i = 0; i < h.length; i += 2) o.push(parseInt(h.substr(i, 2), 16));
  return o;
}
function _rotr32(x, n) { return ((x >>> n) | (x << (32 - n))) >>> 0; }
function _pad(msg) {
  var out = msg.slice();
  var ml = msg.length * 8;
  out.push(0x80);
  while (out.length % 64 !== 56) out.push(0);
  var hi = Math.floor(ml / 4294967296);
  var lo = ml >>> 0;
  out.push((hi >>> 24) & 255, (hi >>> 16) & 255, (hi >>> 8) & 255, hi & 255);
  out.push((lo >>> 24) & 255, (lo >>> 16) & 255, (lo >>> 8) & 255, lo & 255);
  return out;
}
function _wordsToBytes(w) {
  var o = [];
  for (var i = 0; i < w.length; i++) {
    o.push((w[i] >>> 24) & 255, (w[i] >>> 16) & 255, (w[i] >>> 8) & 255,
      w[i] & 255);
  }
  return o;
}
function _hexWords(w) {
  var s = '';
  for (var i = 0; i < w.length; i++) {
    s += ('00000000' + w[i].toString(16)).slice(-8);
  }
  return s;
}
"""

_JS_DIGEST_READABLE_TMPL = """function _digest(msgBytes) {
  var padded = _pad(msgBytes);
  var h = HT.slice();
  for (var off = 0; off < padded.length; off += 64) {
    var w = [];
    for (var i = 0; i < 16; i++) {
      w.push((padded[off + 4 * i] << 24 | padded[off + 4 * i + 1] << 16 |
        padded[off + 4 * i + 2] << 8 | padded[off + 4 * i + 3]) >>> 0);
    }
    for (var i = 16; i < 64; i++) {
      var s0 = _rotr32(w[i - 15], 7) ^ _rotr32(w[i - 15], 18) ^
        (w[i - 15] >>> 3);
      var s1 = _rotr32(w[i - 2], 17) ^ _rotr32(w[i - 2], 19) ^
        (w[i - 2] >>> 10);
      w.push((w[i - 16] + s0 + w[i - 7] + s1) >>> 0);
    }
    var a = h[0], b = h[1], c = h[2], d = h[3];
    var e = h[4], f = h[5], g = h[6], hh = h[7];
    for (var i = 0; i < 64; i++) {
      var S1 = _rotr32(e, 6) ^ _rotr32(e, 11) ^ _rotr32(e, 25);
      var ch = (e & f) ^ (~e & g);
      var t1 = (hh + S1 + ch + KT[i] + w[i]) >>> 0;
      var S0 = _rotr32(a, 2) ^ _rotr32(a, 13) ^ _rotr32(a, 22);
      var mj = (a & b) ^ (a & c);
      var t2 = (S0 + mj) >>> 0;
      hh = g; g = f; f = e; e = (d + t1) >>> 0;
      d = c; c = b; b = a; a = (t1 + t2) >>> 0;
    }
    h[0] = (h[0] + a) >>> 0; h[1] = (h[1] + b) >>> 0;
    h[2] = (h[2] + c) >>> 0; h[3] = (h[3] + d) >>> 0;
    h[4] = (h[4] + e) >>> 0; h[5] = (h[5] + f) >>> 0;
    h[6] = (h[6] + g) >>> 0; h[7] = (h[7] + hh) >>> 0;
  }
  return h;
}
"""

_JS_HMAC_TMPL = """function _hmacHex(keyBytes, msgBytes) {
  var ip = [];
  var op = [];
  for (var i = 0; i < 64; i++) {
    var b = i < keyBytes.length ? keyBytes[i] : 0;
    ip.push(b ^ 0x36);
    op.push(b ^ 0x5c);
  }
  return _hexWords(_digest(op.concat(_wordsToBytes(
    _digest(ip.concat(msgBytes))))));
}
"""

_JS_DECOYS_TMPL = """var _0xd1 = __DECOY_D1__;
var _0xd2 = __DECOY_D2__;
function _0x77(h) { return (((h ^ (_0xd1 * 0)) >>> 0) + _0xd2 * 0) >>> 0; }
"""

# l1 hex-id rename table (word-boundary regex; contract names sign /
# signRequest / handshake are NEVER renamed — they are the candidate seam)
_L1_RENAMES = {
    "_bytesOf": "_0x4a", "_unhex": "_0x51", "_rotr32": "_0x2f", "_pad": "_0x1c",
    "_wordsToBytes": "_0x5d", "_hexWords": "_0x3e", "_digest": "_0x48",
    "_hmacHex": "_0x19", "_kdfHex": "_0x73", "_wrongOut": "_0x58",
    "_newMem": "_0x6f", "_loadBlock": "_0x7c", "_vmRun": "_0x21",
    "_0x77": "_0x66", "_P": "_0x5a",
}


def _minify_l1(src: str, seed: int) -> str:
    """L1 packaging transform: hex identifiers (the decoys are already in
    the template), comment/indent strip. Deterministic: a pure function of
    the source text."""
    for old, new in _L1_RENAMES.items():
        src = re.sub(rf"\b{re.escape(old)}\b", new, src)
    lines = []
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        lines.append(stripped)
    return "\n".join(lines) + "\n"


def _js_constants_block(cfg: dict) -> str:
    return _JS_CONST_TMPL.format(
        key_hex=cfg["key_hex"],
        k_table=", ".join(f"0x{v:08x}" for v in cfg["k"]),
        h_table=", ".join(f"0x{v:08x}" for v in cfg["h"]),
        sep=cfg["sep_code"])


def _js_wrong_out(seed: int) -> str:
    poison = _u32(seed, 91)
    return (
        "function _wrongOut(x) {\n"
        "  var n = (x && x.length) ? x.length : 0;\n"
        "  return ('00000000000000000000000000000000' +\n"
        f"    ((0x{poison:08x} ^ ((n + 1) * 2654435761)) >>> 0)"
        ".toString(16)).slice(-32);\n"
        "}\n")


def _render_release_js(family: str, seed: int, cfg: dict, rung: str) -> str:
    """Readable l0 artifact for the release families (the input to the l1
    minify transform AND the l2 obfuscator run); l3 swaps the digest core
    for the VM rung; l1 post-processes with _minify_l1."""
    ad_seed = _u32(seed, 92)
    head = (
        f"// CONSTRUCTED eval target (family {family}, rung {rung}, "
        "eval-v1.1, #332).\n"
        "// NOT malware; no real workspace data: every constant below is\n"
        "// minted by scripts/eval_targets.py from the unit seed. The\n"
        "// derivation core is the generator's mod-crypto cipher (mutated\n"
        "// SHA-256 + HMAC) — stock crypto is wrong by construction.\n")
    parts = [head, _JS_ANTIDEBUG_TMPL.replace(
                 "__AD_SEED__", f"0x{ad_seed:08x}"),
             _js_constants_block(cfg)]
    if rung == "l1":
        d1, d2 = _u32(seed, 93), _u32(seed, 94)
        parts.append(_JS_DECOYS_TMPL.replace(
            "__DECOY_D1__", f"0x{d1:08x}").replace(
            "__DECOY_D2__", f"0x{d2:08x}"))
    parts.append(_JS_HELPERS_TMPL)
    if rung == "l3":
        _vm_self_test(cfg, seed)
        parts.append(_render_vm_js(cfg, seed))
    else:
        parts.append(_JS_DIGEST_READABLE_TMPL)
    parts.append(_JS_HMAC_TMPL)
    parts.append(_js_wrong_out(seed))
    key_bytes = "_0x51(KX)" if rung == "l1" else "_unhex(KX)"
    if family == "mod-crypto-js":
        parts.append(f"""function sign(input) {{
  if (!AD.ok()) return _wrongOut(input);
  return _hmacHex({key_bytes}, _bytesOf(String(input)));
}}

module.exports = {{ sign: sign }};

if (typeof require !== 'undefined' && require.main === module) {{
  console.log(JSON.stringify({{ in: 'alpha', out: sign('alpha') }}));
}}
""")
    elif family == "web-pack-sign":
        parts.append(f"""function sign(request) {{
  if (!AD.ok()) return _wrongOut(request && request.body);
  var bodySha = _hexWords(_digest(_bytesOf(String(request.body))));
  var canon = [String(request.method), String(request.path), bodySha,
    String(request.seq)].join(SEPCH);
  return _hmacHex({key_bytes}, _bytesOf(canon));
}}

module.exports = {{ sign: sign }};
""")
    elif family == "req-sign":
        sorted_flag = "true" if cfg.get("sort_headers") else "false"
        parts.append(f"""function signRequest(request) {{
  if (!AD.ok()) return _wrongOut(request && request.body);
  var pairs = (request.headers || []).map(function (p) {{
    return [String(p[0]), String(p[1])];
  }});
  if ({sorted_flag}) {{
    pairs.sort(function (x, y) {{
      return x[0] < y[0] ? -1 : (x[0] > y[0] ? 1 : 0);
    }});
  }}
  var blob = pairs.map(function (p) {{ return p[0] + ':' + p[1]; }})
    .join(SEPCH);
  var hh = _hexWords(_digest(_bytesOf(blob)));
  var bodySha = _hexWords(_digest(_bytesOf(String(request.body))));
  var canon = [String(request.method), hh, bodySha,
    String(request.path)].join(SEPCH);
  return _hmacHex({key_bytes}, _bytesOf(canon));
}}

module.exports = {{ signRequest: signRequest }};
""")
    elif family == "net-verify-license":
        rounds = int(cfg.get("rounds", 2))
        parts.append(f"""function _kdfHex(challengeHex) {{
  var secret = {key_bytes};
  var k = _digest(secret.concat(_unhex(challengeHex)));
  for (var r = 1; r < {rounds}; r++) k = _digest(_wordsToBytes(k));
  return k;
}}

async function handshake(opts) {{
  var chResp = await fetch(opts.serverUrl + '/challenge', {{
    method: 'POST',
    headers: {{ 'content-type': 'application/json' }},
    body: JSON.stringify({{ i: opts.i, client_nonce: opts.clientNonce,
      device: opts.device }})
  }});
  var doc = await chResp.json();
  if (!AD.ok()) {{
    await fetch(opts.serverUrl + '/verify', {{
      method: 'POST',
      headers: {{ 'content-type': 'application/json' }},
      body: JSON.stringify({{ session: doc.session,
        response: _wrongOut(opts.device) }})
    }});
    return {{ session: doc.session }};
  }}
  var sk = _kdfHex(String(doc.challenge));
  var payload = [String(doc.challenge), String(opts.clientNonce),
    String(opts.device), String(opts.i)].join(SEPCH);
  var response = _hmacHex(_wordsToBytes(sk), _bytesOf(payload));
  var vResp = await fetch(opts.serverUrl + '/verify', {{
    method: 'POST',
    headers: {{ 'content-type': 'application/json' }},
    body: JSON.stringify({{ session: doc.session, response: response }})
  }});
  var verdict = await vResp.json();
  return {{ session: doc.session, valid: verdict.valid === true }};
}}

module.exports = {{ handshake: handshake }};
""")
    else:  # pragma: no cover
        raise ValueError(f"unknown release family: {family}")
    src = "".join(parts)
    return _minify_l1(src, seed) if rung == "l1" else src


# l2: the ONLY externally tooled rung — javascript-obfuscator@5.8.0, STRONG
# preset per the #332 card. Non-determinism source: selfDefending +
# stringArray rotate/shuffle are randomized by the tool; the COMMITTED
# artifact is the pinned face (re-mints are behavior-verified, not
# byte-verified), task.yaml labels determinism=seed-pinned.
OBFUSCATOR_LABEL = "javascript-obfuscator@5.8.0"
_OBFUSCATOR_CONFIG = {
    "compact": True,
    "controlFlowFlattening": True,
    "controlFlowFlatteningThreshold": 1,
    "deadCodeInjection": True,
    "deadCodeInjectionThreshold": 0.5,
    "stringArray": True,
    "stringArrayThreshold": 1,
    "stringArrayEncoding": ["rc4"],
    "stringArrayRotate": True,
    "stringArrayShuffle": True,
    "stringArrayWrappersCount": 2,
    "stringArrayWrappersType": "function",
    "numbersToExpressions": True,
    "splitStrings": True,
    "splitStringsChunkLength": 8,
    "transformObjectKeys": True,
    "unicodeEscapeSequence": True,
    "selfDefending": True,
    "renameGlobals": False,
    "debugProtection": False,
    "disableConsoleOutput": False,
}

# node seam-probe: written to a temp file and run as `node <file> <artifact>
# <seam>` (argv form, no shell, no interpolated snippets)
_SEAM_PROBE_JS = (
    "const m = require(process.argv[2]);\n"
    "const seam = process.argv[3];\n"
    "process.stdout.write(typeof m[seam]);\n"
    "process.exit(typeof m[seam] === 'function' ? 0 : 1);\n")


def _tool_on_path(cmd: str):
    import shutil
    return shutil.which(cmd)


def mint_l2_obfuscated(src: str, family: str) -> str | None:
    """Ship the l0-equivalent seed source through javascript-obfuscator and
    return the obfuscated TEXT. Returns None (a structured SKIP upstream)
    when npx is unavailable — never fabricates a fake-l2 artifact."""
    import subprocess
    import tempfile
    if _tool_on_path("npx") is None:
        return None
    with tempfile.TemporaryDirectory(prefix="kunglao-l2-") as td:
        tdir = Path(td)
        cfg_file = tdir / "obf-config.json"
        cfg_file.write_text(json.dumps(_OBFUSCATOR_CONFIG), encoding="utf-8")
        src_file = tdir / f"seed-{family}.js"
        src_file.write_text(src, encoding="utf-8")
        out_file = tdir / "obfuscated.js"
        proc = subprocess.run(
            ["npx", "--yes", "javascript-obfuscator", str(src_file),
             "--output", str(out_file), "--config", str(cfg_file)],
            capture_output=True, text=True, timeout=300)
        if proc.returncode != 0 or not out_file.is_file():
            raise RuntimeError(
                f"javascript-obfuscator failed (rc={proc.returncode}): "
                f"{proc.stderr[-400:]}")
        # behavioral spot check: the obfuscated artifact must keep its seam
        if _tool_on_path("node") is not None:
            probe_file = tdir / "seam-probe.js"
            probe_file.write_text(_SEAM_PROBE_JS, encoding="utf-8")
            seam = FAMILIES[family]["anchor_fn"]
            probe = subprocess.run(
                ["node", str(probe_file), str(out_file), seam],
                capture_output=True, text=True, timeout=60)
            if probe.returncode != 0:
                raise RuntimeError(
                    f"obfuscated artifact lost its contract seam ({seam}): "
                    f"{probe.stderr[-400:]}")
        return out_file.read_text(encoding="utf-8")


def render_release(family: str, seed: int, rung: str) -> str:
    """The rung-dispatching renderer. l2 returns the PRE-obfuscation
    source (the artifact actually minted by write_task_unit goes through
    javascript-obfuscator; l2 re-mints are behavior-pinned only)."""
    if rung not in RUNG_ORACLES:
        raise ValueError(f"unknown rung {rung!r}; valid: {sorted(RUNG_ORACLES)}")
    return _render_release_js(family, seed, derive_cfg(family, seed, rung),
                              rung)


RENDERERS = {"go-arx": render_go, "js-sign": render_js, "py-derive": render_py}


# --------------------------------------------------------------- unit minting
RELEASE_FAMILIES = ("web-pack-sign", "net-verify-license", "req-sign",
                    "mod-crypto-js")

_ANCHORS = {
    "go-arx": {
        "goal_verbatim": (
            "Recover the three mutated constants embedded in "
            "target/sample_kdf.go and re-implement the KDF pipeline so that "
            "it reproduces the captured input/output pairs byte-exact."),
        "success_criterion": (
            "A re-implementation carrying the three recovered constants that "
            "reproduces the 16 captured pairs and the checker-minted stdin "
            "probes."),
        "verification_method": "reproduction",
    },
    "js-sign": {
        "goal_verbatim": (
            "Deobfuscate target/sign_bundle.js, recover the two load-bearing "
            "round constants (ignore the decoys), and re-expose a sign() that "
            "reproduces the captured (input, output) pairs."),
        "success_criterion": (
            "A sign() re-implementation carrying the two recovered constants "
            "that reproduces every captured and checker-minted pair."),
        "verification_method": "reproduction",
    },
    "py-derive": {
        "goal_verbatim": (
            "Recover the three parameters of the derivation in "
            "target/derive.py and re-implement derive(data) -> int so it "
            "reproduces the reference outputs on arbitrary inputs."),
        "success_criterion": (
            "A derive() re-implementation that reproduces every published and "
            "checker-minted probe output exactly."),
        "verification_method": "reproduction",
    },
    "web-pack-sign": {
        "goal_verbatim": (
            "Unpack the bundler-obfuscated signer (target/web_sign_bundle.js), "
            "recover the embedded key and canonical form, and re-expose a "
            "sign(request) that reproduces the captured signatures."),
        "success_criterion": (
            "A sign(request) re-implementation reproducing every published "
            "and checker-minted request signature byte-exact — the body "
            "digest comes from the mutated mod-crypto core, so stock-crypto "
            "signers fail by construction."),
        "verification_method": "reproduction",
    },
    "net-verify-license": {
        "goal_verbatim": (
            "Reverse the license client SDK sample "
            "(target/license_client.js), recover the challenge-response "
            "derivation (KDF over the mutated core + HMAC over the canonical "
            "payload), and re-expose a handshake(opts) that completes the "
            "protocol against the checker-hosted loopback mock server."),
        "success_criterion": (
            "The mock license server validates every session server-side — "
            "on the published AND freshly minted challenges; the no-egress "
            "guarantee holds (loopback bind, ephemeral port, base URL via "
            "argv, no host literal in any artifact)."),
        "verification_method": "replay-evidence",
    },
    "req-sign": {
        "goal_verbatim": (
            "Recover the canonical-request form (method + ordered-headers-"
            "hash + body-sha + path, HMAC over the mutated core) from "
            "target/request_signer.js and re-expose signRequest(request) "
            "reproducing the captured signatures."),
        "success_criterion": (
            "A signRequest(request) re-implementation reproducing every "
            "published and minted signature; at l2 the canonical sorts "
            "header names, so permuted header order must yield the identical "
            "signature."),
        "verification_method": "reproduction",
    },
    "mod-crypto-js": {
        "goal_verbatim": (
            "Deobfuscate the signer bundle (target/modcrypto_bundle.js), "
            "recover the mutated-cipher constants, and re-expose sign(input) "
            "reproducing the captured pairs."),
        "success_criterion": (
            "A sign() re-implementation on the MUTATED core reproducing "
            "every published and minted pair; a stock HMAC-SHA256 candidate "
            "fails every pair (the named anti-standard regression)."),
        "verification_method": "reproduction",
    },
}

_CANDIDATE_CONTRACT = {
    "go-arx": ("A Go program that is INPUT-AGNOSTIC: reads one JSON object "
               "per line from stdin ({\"i\": N, \"in\": X}) and prints one "
               "JSON object per line ({\"i\": N, \"in\": X, \"out\": Y}) "
               "with out = the pipeline applied to in. The published capture "
               "(" + GO_INPUT_FORMULA + ") is the fixed face; the checker "
               "additionally drives freshly minted stdin probes, so a PASS "
               "requires the actual derivation — a constants+lookup shortcut "
               "fails on inputs it never saw."),
    "js-sign": ("A Node module exporting sign(inputString) -> 8-hex-char "
                "lowercase string."),
    "py-derive": ("A Python module exposing derive(data: bytes) -> int."),
    "web-pack-sign": ("A Node module exporting sign(request) -> 64-hex-char "
                      "lowercase string, request = {method, path, body, "
                      "seq}."),
    "net-verify-license": ("A Node module exporting async "
                           "handshake({serverUrl, i, clientNonce, device}) "
                           "-> {session, ...}: the module performs the FULL "
                           "challenge/response protocol against the "
                           "checker-hosted loopback mock server (base URL "
                           "arrives via opts only — no host literal in the "
                           "artifact)."),
    "req-sign": ("A Node module exporting signRequest(request) -> 64-hex-"
                 "char lowercase string, request = {method, path, headers: "
                 "[[name, value], ...], body}."),
    "mod-crypto-js": ("A Node module exporting sign(inputString) -> 64-hex-"
                      "char lowercase string over the mutated core."),
}

_GOAL_NOTE = {
    "go-arx": ("pair-match tolerance keeps the case-admission C2 shape "
               "(>= 20 of 26); the minted stdin probes close the "
               "constants+table shortcut."),
    "js-sign": "round-trip face runs the exposed sign() over published + minted probes.",
    "py-derive": "round-trip face runs derive() over published + checker-minted probes.",
    "web-pack-sign": ("replay-roundtrip runs sign() over published + minted "
                      "request probes (anti-digest-table); the body digest "
                      "is the mutated cipher — stock-crypto signers and "
                      "key-copy/no-canonicalization cheats fail the minted "
                      "face."),
    "net-verify-license": ("the oracle is SERVER-SIDE: the checker-hosted "
                           "loopback mock recomputes "
                           "HMAC(KDF(challenge, secret), canonical_payload) "
                           "from the seed and validates every session on "
                           "published + minted challenges; no egress — bind "
                           "127.0.0.1 ephemeral, base URL via argv."),
    "req-sign": ("l1 canonicalizes headers in the GIVEN order; l2 sorts "
                 "header names (permuted header order -> identical "
                 "signature); replay face runs signRequest() over published "
                 "+ minted requests."),
    "mod-crypto-js": ("the anti-standard regression face: a stock "
                      "HMAC-SHA256 candidate fails every pair by "
                      "construction; constant-hit armed at l1, honestly "
                      "disarmed at l2 (rc4 stringArray) and l3 (VM "
                      "bytecode) — behavior is the oracle there."),
}


def _published_count(family: str) -> int:
    return {"go-arx": 16, "js-sign": 10, "py-derive": 12,
            "web-pack-sign": 12, "req-sign": 12, "net-verify-license": 6,
            "mod-crypto-js": 10}[family]


def _minted_count(family: str) -> int:
    return {"go-arx": 10, "js-sign": 10, "py-derive": 12,
            "web-pack-sign": 8, "req-sign": 8, "net-verify-license": 6,
            "mod-crypto-js": 10}[family]


def _constants_public(family: str, cfg: dict) -> dict:
    if family == "go-arx":
        return {"k0": cfg["k0"], "z": cfg["z"], "rot_base": cfg["rot_base"]}
    if family == "js-sign":
        return {"c1": cfg["c1"], "c2": cfg["c2"]}
    if family in ("web-pack-sign", "req-sign", "mod-crypto-js"):
        return {"key_hex": cfg["key_hex"], "sep_code": cfg["sep_code"]}
    if family == "net-verify-license":
        return {"key_hex": cfg["key_hex"], "device": cfg["device"]}
    return {"offset": cfg["offset"], "prime": cfg["prime"], "fold": cfg["fold"]}


def build_task_unit(family: str, seed: int, task_id: str,
                    rung: str | None = None) -> dict:
    """Everything the unit needs, in memory: task.yaml payload, target
    source, ground_truth payload, checker shim. ``rung`` selects the
    release packaging ladder (l0/l1/l2/l3); smoke families ignore it.

    For rung == "l2", ``target_source`` is the PRE-obfuscation seed
    source; write_task_unit ships it through javascript-obfuscator (the
    committed artifact) — l2 re-mints are behavior-pinned, not
    byte-pinned (selfDefending/stringArray randomization, documented).
    """
    meta = FAMILIES[family]
    is_release = meta.get("tier") == "release"
    rung = rung if (is_release and rung) else None
    if is_release:
        cfg = derive_cfg(family, seed, rung or "l1")
    else:
        cfg = derive_cfg(family, seed)
    published = published_pairs(family, cfg, _published_count(family))
    if is_release:
        task = {
            "schema": SCHEMA_TASK,
            "task_id": task_id,
            "eval_version": "eval-v1.1",
            "tier": "release",
            "source": "constructed",
            "family": family,
            "seed": seed,
            "rung": rung,
            "anchors": dict(_ANCHORS[family]),
            "workspace_scaffold": {
                "language": meta["language"],
                "files": [meta["target"]],
                "entry": meta["target"],
                "candidate_contract": _CANDIDATE_CONTRACT[family],
            },
            "checker": {
                "kind": "replay-roundtrip",
                "oracles": list(RUNG_ORACLES[rung]),
                "entrypoint": "checker.py",
                "metrics": ["ttc_seconds", "dispatch_count",
                            "pass_at_k_contribution", "converged"],
                "thresholds": dict(RUNG_THRESHOLDS[rung]),
            },
            "ground_truth": {"file": "ground_truth.json",
                             "space_bits": meta["space_bits"]},
            "contamination": {
                "held_out": True,
                "distiller_excluded": True,
                "provenance": "constructed",
            },
            "anti_debug": {
                "traps": list(ANTI_DEBUG_TRAPS),
                "clean_env_guarantee": ANTI_DEBUG_NOTE,
                "self_defending": "pinned" if rung == "l2"
                else "generator-native",
            },
            "tooling": {
                "l0": {"packaging": "readable-baseline"},
                "l1": {"packaging": "minify+hex-ids+decoys"},
                "l2": {
                    "obfuscator": OBFUSCATOR_LABEL,
                    "determinism": "seed-pinned",
                    "preset": "strong",
                    "note": ("selfDefending/stringArray rotation randomize "
                             "BYTES per mint; the committed artifact is the "
                             "pinned face and behavior is verified "
                             "(pretty-print proof breaks it)"),
                },
                "l3": {"packaging": "vm-bytecode",
                       "note": ("python transform compiles the compression "
                                "to seed-mutated custom opcodes + JS "
                                "interpreter loop; mint-time verifier "
                                "proves bytecode == model")},
            }[rung],
        }
    else:
        task = {
            "schema": SCHEMA_TASK,
            "task_id": task_id,
            "eval_version": "eval-v1",
            "tier": "smoke",
            "source": "constructed",
            "family": family,
            "seed": seed,
            "anchors": dict(_ANCHORS[family]),
            "workspace_scaffold": {
                "language": meta["language"],
                "files": [meta["target"]],
                "entry": meta["target"],
                "candidate_contract": _CANDIDATE_CONTRACT[family],
            },
            "checker": {
                "kind": meta["kind"],
                "oracles": list(meta["oracles"]),
                "entrypoint": "checker.py",
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
        "constants": _constants_public(family, cfg),
        "space_bits": meta["space_bits"],
        "published_pairs": published,
        "minted_probe_count": _minted_count(family),
        "note": _GOAL_NOTE[family],
    }
    if is_release:
        # the FULL mutated core rides with the unit so the checker model
        # recomputes expected outputs without re-deriving (ground truth by
        # construction, same generator)
        ground_truth["core"] = cfg
    if family == "js-sign":
        ground_truth["decoy_constants"] = {"d1": cfg["decoys"][0],
                                           "d2": cfg["decoys"][1]}
    shim = (
        "#!/usr/bin/env python3\n"
        f"# checker.py — {task_id} mechanical-checker shim (#299/#332).\n"
        "# Standalone entry for the task unit: delegates to the shared\n"
        "# mechanical checker with this task directory. Default candidate is\n"
        "# the constructed target itself (self-check); pass --candidate to\n"
        "# grade an arm's re-implementation (the #236 control-arm surface).\n"
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
        "        argv += [\"--candidate\", str(_HERE / "
        f"{meta['target']!r})]\n"
        "    raise SystemExit(eval_checker.main([\"--task\", str(_HERE)] + argv))\n")
    if is_release:
        target_source = _render_release_js(family, seed, cfg, rung)
    else:
        target_source = RENDERERS[family](cfg)
    return {"task": task, "target_path": meta["target"],
            "target_source": target_source,
            "ground_truth": ground_truth, "checker_shim": shim}


def write_task_unit(family: str, seed: int, task_id: str, root: Path,
                    rung: str | None = None) -> Path:
    """Mint one task unit onto disk (idempotent per (family, seed, rung)).

    rung == "l2" ships the seed source through javascript-obfuscator at
    mint time; when npx is absent the unit is SKIPPED structurally (never
    faked)."""
    unit = build_task_unit(family, seed, task_id, rung=rung)
    is_release = unit["task"].get("tier") == "release"
    eff_rung = unit["task"].get("rung")
    target_text = unit["target_source"]
    if is_release and eff_rung == "l2":
        minted = mint_l2_obfuscated(target_text, family)
        if minted is None:
            print(f"SKIP {task_id}: npx/javascript-obfuscator unavailable "
                  "(toolchain-absent = structured SKIP)")
            return Path(root) / task_id
        target_text = minted
    tdir = Path(root) / task_id
    (tdir / "target").mkdir(parents=True, exist_ok=True)
    (tdir / "task.yaml").write_text(
        yaml.safe_dump(unit["task"], sort_keys=False, allow_unicode=True),
        encoding="utf-8")
    (tdir / unit["target_path"]).write_text(target_text, encoding="utf-8")
    (tdir / "ground_truth.json").write_text(
        json.dumps(unit["ground_truth"], indent=2) + "\n", encoding="utf-8")
    shim = tdir / "checker.py"
    shim.write_text(unit["checker_shim"], encoding="utf-8")
    shim.chmod(0o755)
    return tdir


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="eval_targets.py",
        description="Mint #299/#332 constructed eval-task units "
                    "(family:seed:task_id[:rung]).")
    ap.add_argument("--root", default="eval/v1/tasks/smoke",
                    help="task corpus root (default: eval/v1/tasks/smoke)")
    ap.add_argument("--mint", action="append", default=[],
                    help="family:seed:task_id[:rung] (repeatable; rung "
                         "l0/l1/l2/l3 for release families)")
    args = ap.parse_args(argv)
    if not args.mint:
        ap.error("nothing to mint: pass --mint family:seed:task_id[:rung]")
    from pathlib import Path as _P
    for spec in args.mint:
        pieces = spec.split(":")
        if len(pieces) == 3:
            family, seed_s, task_id = pieces
            rung = None
        elif len(pieces) == 4:
            family, seed_s, task_id, rung = pieces
        else:
            ap.error(f"bad --mint spec {spec!r} (want "
                     "family:seed:task_id[:rung])")
        tdir = write_task_unit(family, int(seed_s), task_id, _P(args.root),
                               rung=rung)
        print(f"MINTED {task_id} ({family}, seed={seed_s}"
              f"{', rung=' + rung if rung else ''}) -> {tdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
