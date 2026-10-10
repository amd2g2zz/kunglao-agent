#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_crypto.py — the mod-crypto core (#332 addition A).

A seed-derived mutation generator over two standard constructions:

  mod-AES-128   S-box = standard FIPS-197 S-box composed with a seeded
                permutation (bijective by construction); Rcon = standard
                Rcon XOR a seeded mask. Round structure is stock AES-128
                (10 rounds, stock key schedule shape).
  mod-SHA-256   initial H constants and the K table = FIPS-180 values XOR
                seeded 32-bit masks. Padding, schedule and compression
                steps are stock.

Contract (the anti-standard property): seed 0 selects the STANDARD
parameters (identity mutation) — FIPS-197/FIPS-180 test vectors pin the
implementation; every nonzero seed diverges from stock on the FIRST block,
so a hashlib / stock-AES candidate is wrong by construction on every
probe. This is the reference the native KDFs are built ON: the arm/win
KDFs are counter-mode mod-SHA (``kdf_sha``); the SMC payload IS a
mod-crypto implementation (``payload_transform``: SHA digest split into an
AES key + block).

Deterministic, pure stdlib, no crypto library: the only floating data is
the seed. The PRNG is the shared generator's SplitMix32 stream (imported
from eval_targets so every #299/#332 mint derives from one function).
"""
from __future__ import annotations

from eval_targets import M32, _u32

# ---- standard parameters (public FIPS constants) -------------------------
STANDARD_SBOX = [
    0x63, 0x7c, 0x77, 0x7b, 0xf2, 0x6b, 0x6f, 0xc5, 0x30, 0x01, 0x67, 0x2b,
    0xfe, 0xd7, 0xab, 0x76, 0xca, 0x82, 0xc9, 0x7d, 0xfa, 0x59, 0x47, 0xf0,
    0xad, 0xd4, 0xa2, 0xaf, 0x9c, 0xa4, 0x72, 0xc0, 0xb7, 0xfd, 0x93, 0x26,
    0x36, 0x3f, 0xf7, 0xcc, 0x34, 0xa5, 0xe5, 0xf1, 0x71, 0xd8, 0x31, 0x15,
    0x04, 0xc7, 0x23, 0xc3, 0x18, 0x96, 0x05, 0x9a, 0x07, 0x12, 0x80, 0xe2,
    0xeb, 0x27, 0xb2, 0x75, 0x09, 0x83, 0x2c, 0x1a, 0x1b, 0x6e, 0x5a, 0xa0,
    0x52, 0x3b, 0xd6, 0xb3, 0x29, 0xe3, 0x2f, 0x84, 0x53, 0xd1, 0x00, 0xed,
    0x20, 0xfc, 0xb1, 0x5b, 0x6a, 0xcb, 0xbe, 0x39, 0x4a, 0x4c, 0x58, 0xcf,
    0xd0, 0xef, 0xaa, 0xfb, 0x43, 0x4d, 0x33, 0x85, 0x45, 0xf9, 0x02, 0x7f,
    0x50, 0x3c, 0x9f, 0xa8, 0x51, 0xa3, 0x40, 0x8f, 0x92, 0x9d, 0x38, 0xf5,
    0xbc, 0xb6, 0xda, 0x21, 0x10, 0xff, 0xf3, 0xd2, 0xcd, 0x0c, 0x13, 0xec,
    0x5f, 0x97, 0x44, 0x17, 0xc4, 0xa7, 0x7e, 0x3d, 0x64, 0x5d, 0x19, 0x73,
    0x60, 0x81, 0x4f, 0xdc, 0x22, 0x2a, 0x90, 0x88, 0x46, 0xee, 0xb8, 0x14,
    0xde, 0x5e, 0x0b, 0xdb, 0xe0, 0x32, 0x3a, 0x0a, 0x49, 0x06, 0x24, 0x5c,
    0xc2, 0xd3, 0xac, 0x62, 0x91, 0x95, 0xe4, 0x79, 0xe7, 0xc8, 0x37, 0x6d,
    0x8d, 0xd5, 0x4e, 0xa9, 0x6c, 0x56, 0xf4, 0xea, 0x65, 0x7a, 0xae, 0x08,
    0xba, 0x78, 0x25, 0x2e, 0x1c, 0xa6, 0xb4, 0xc6, 0xe8, 0xdd, 0x74, 0x1f,
    0x4b, 0xbd, 0x8b, 0x8a, 0x70, 0x3e, 0xb5, 0x66, 0x48, 0x03, 0xf6, 0x0e,
    0x61, 0x35, 0x57, 0xb9, 0x86, 0xc1, 0x1d, 0x9e, 0xe1, 0xf8, 0x98, 0x11,
    0x69, 0xd9, 0x8e, 0x94, 0x9b, 0x1e, 0x87, 0xe9, 0xce, 0x55, 0x28, 0xdf,
    0x8c, 0xa1, 0x89, 0x0d, 0xbf, 0xe6, 0x42, 0x68, 0x41, 0x99, 0x2d, 0x0f,
    0xb0, 0x54, 0xbb, 0x16,
]
STANDARD_RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36]
STANDARD_H = [
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
]
STANDARD_K = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
    0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
    0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
    0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
    0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
    0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
    0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
    0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]


# ---- seed-derived mutations ----------------------------------------------
def mutated_sbox(seed: int) -> list[int]:
    """Standard S-box composed with a seeded permutation (identity at
    seed 0). A composition of bijections is a bijection."""
    if seed == 0:
        return list(STANDARD_SBOX)
    sbox = list(STANDARD_SBOX)
    # Fisher-Yates over the derived stream
    for i in range(255, 0, -1):
        j = _u32(seed, 0x5B0 + i) % (i + 1)
        sbox[i], sbox[j] = sbox[j], sbox[i]
    return sbox


def mutated_rcon(seed: int) -> list[int]:
    if seed == 0:
        return list(STANDARD_RCON)
    return [(r ^ (_u32(seed, 0x5C0 + i) & 0xFF)) or r for i, r in
            enumerate(STANDARD_RCON)]


def mutated_h(seed: int) -> list[int]:
    if seed == 0:
        return list(STANDARD_H)
    return [h ^ _u32(seed, 0x5D0 + i) for i, h in enumerate(STANDARD_H)]


def mutated_k(seed: int) -> list[int]:
    if seed == 0:
        return list(STANDARD_K)
    return [k ^ _u32(seed, 0x5E0 + i) for i, k in enumerate(STANDARD_K)]


# ---- mod-SHA-256 -----------------------------------------------------------
def _rotr(x: int, n: int) -> int:
    return ((x >> n) | (x << (32 - n))) & M32


def _sha_blocks(msg: bytes) -> list[bytes]:
    bit_len = (len(msg) * 8) & 0xFFFFFFFFFFFFFFFF
    padded = msg + b"\x80" + b"\x00" * ((55 - len(msg)) % 64) + \
        bit_len.to_bytes(8, "big")
    return [padded[i * 64:i * 64 + 64] for i in range(len(padded) // 64)]


def mod_sha256(seed: int, msg: bytes) -> bytes:
    """SHA-256 shape with the seed-mutated H/K (standard at seed 0)."""
    h = mutated_h(seed)
    k = mutated_k(seed)
    for block in _sha_blocks(msg):
        w = [int.from_bytes(block[i * 4:i * 4 + 4], "big") for i in range(16)]
        for i in range(16, 64):
            s0 = _rotr(w[i - 15], 7) ^ _rotr(w[i - 15], 18) ^ (w[i - 15] >> 3)
            s1 = _rotr(w[i - 2], 17) ^ _rotr(w[i - 2], 19) ^ (w[i - 2] >> 10)
            w.append((w[i - 16] + s0 + w[i - 7] + s1) & M32)
        a, b, c, d, e, f, g, hh = h
        for i in range(64):
            s1 = _rotr(e, 6) ^ _rotr(e, 11) ^ _rotr(e, 25)
            ch = (e & f) ^ (~e & g)
            t1 = (hh + s1 + ch + k[i] + w[i]) & M32
            s0 = _rotr(a, 2) ^ _rotr(a, 13) ^ _rotr(a, 22)
            maj = (a & b) ^ (a & c) ^ (b & c)
            t2 = (s0 + maj) & M32
            hh, g, f, e = g, f, e, (d + t1) & M32
            d, c, b, a = c, b, a, (t1 + t2) & M32
        h = [(x + y) & M32 for x, y in zip(h, [a, b, c, d, e, f, g, hh])]
    return b"".join(x.to_bytes(4, "big") for x in h)


# ---- mod-AES-128 -----------------------------------------------------------
def _xtime(a: int, _poly: int = 0x1b) -> int:
    a <<= 1
    return (a ^ _poly) & 0xFF if a & 0x100 else a


def _aes_expand_key(key: bytes, sbox: list[int], rcon: list[int]) -> list[int]:
    words = [list(key[i * 4:i * 4 + 4]) for i in range(4)]
    for i in range(4, 44):
        t = list(words[i - 1])
        if i % 4 == 0:
            t = t[1:] + t[:1]
            t = [sbox[b] for b in t]
            t[0] ^= rcon[i // 4 - 1]
        words.append([words[i - 4][j] ^ t[j] for j in range(4)])
    return [b for w in words for b in w]


def aes128_block(seed: int, block: bytes, key: bytes) -> bytes:
    """One stock-shaped AES-128 encryption (10 rounds) with the seed-mutated
    S-box / Rcon (standard at seed 0)."""
    sbox = mutated_sbox(seed)
    rcon = mutated_rcon(seed)
    rk = _aes_expand_key(key, sbox, rcon)
    s = [block[i] ^ rk[i] for i in range(16)]
    for rnd in range(10):
        s = [sbox[b] for b in s]
        s = [s[(i + 4 * (i % 4)) % 16] for i in range(16)]
        if rnd < 9:
            for c in range(4):
                col = s[c * 4:c * 4 + 4]
                s[c * 4 + 0] = _xtime(col[0]) ^ _xtime(col[1]) ^ col[1] ^ col[2] ^ col[3]
                s[c * 4 + 1] = col[0] ^ _xtime(col[1]) ^ _xtime(col[2]) ^ col[2] ^ col[3]
                s[c * 4 + 2] = col[0] ^ col[1] ^ _xtime(col[2]) ^ _xtime(col[3]) ^ col[3]
                s[c * 4 + 3] = _xtime(col[0]) ^ col[0] ^ col[1] ^ col[2] ^ _xtime(col[3])
        off = (rnd + 1) * 16
        s = [s[i] ^ rk[off + i] for i in range(16)]
    return bytes(s)


# ---- the two consumption shapes -------------------------------------------
def kdf_sha(seed: int, data: bytes, blocks: int = 2) -> bytes:
    """Counter-mode mod-SHA KDF: the arm/win KDFs are built ON this."""
    out = bytearray()
    for j in range(blocks):
        out += mod_sha256(seed, data + j.to_bytes(4, "little"))
    return bytes(out)


def payload_transform(seed: int, data: bytes) -> bytes:
    """The mod-crypto mix the SMC payload IS: SHA digest split into an AES
    key (first half) and block (second half), one mutated-AES block out."""
    digest = mod_sha256(seed, data)
    return aes128_block(seed, digest[16:32], digest[0:16])
