# -*- coding: utf-8 -*-
"""tests/test_constants_ref_693.py — the constant-table provenance suite.

Every word in ``rlvr.constants_ref`` is mechanically pinned here by a
DIGEST ROUNDTRIP: a compact pure-python re-implementation of each
family's compression function that READS the module's own tables (IV +
round constants) must reproduce ``hashlib`` digests (or the standard's
published known-answer vector). A wrong, missing, or truncated table
word changes the digest and fails the roundtrip — the exact defect
class a prose "cross-checked" claim cannot catch (a genuine SHA-1
constant set used to classify as mutated when the fifth IV register
was absent; that regression is pinned by test_sha1_word_set_classifies_exact).

Families and their check:
  - md5      compact MD5 (RFC 1321) vs hashlib on empty / abc /
             multi-block vectors;
  - sha1     compact SHA-1 (FIPS 180-4) vs hashlib — exercises all
             FIVE IV registers;
  - sha256   compact SHA-256 (FIPS 180-4) vs hashlib;
  - sm3      compact SM3 (GB/T 32905) vs the standard's published
             "abc" known-answer vector, plus hashlib's sm3 when the
             local OpenSSL provides it.

All vectors are public standard values (no workspace data).
"""
from __future__ import annotations

import hashlib
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from rlvr import constants_ref  # noqa: E402

_MD5_S = ((7, 12, 17, 22) * 4 + (5, 9, 14, 20) * 4
          + (4, 11, 16, 23) * 4 + (6, 10, 15, 21) * 4)


def _rotl(x: int, n: int) -> int:
    return ((x << n) | (x >> (32 - n))) & 0xFFFFFFFF


def _rotr(x: int, n: int) -> int:
    return ((x >> n) | (x << (32 - n))) & 0xFFFFFFFF


def _md5(msg: bytes, iv: tuple[int, ...], t: tuple[int, ...]) -> str:
    """Compact MD5 whose constants are INJECTED from the module tables."""
    a0, b0, c0, d0 = iv
    ml = len(msg) * 8
    msg = msg + b"\x80"
    while len(msg) % 64 != 56:
        msg += b"\x00"
    msg += struct.pack("<Q", ml)
    a, b, c, d = a0, b0, c0, d0
    for off in range(0, len(msg), 64):
        m = list(struct.unpack("<16I", msg[off:off + 64]))
        aa, bb, cc, dd = a, b, c, d
        for i in range(64):
            if i < 16:
                f, g = (b & c) | (~b & d), i
            elif i < 32:
                f, g = (d & b) | (~d & c), (5 * i + 1) % 16
            elif i < 48:
                f, g = b ^ c ^ d, (3 * i + 5) % 16
            else:
                f, g = c ^ (b | ~d), (7 * i) % 16
            f = (f + a + t[i] + m[g]) & 0xFFFFFFFF
            a, d, c, b = d, c, b, (b + _rotl(f, _MD5_S[i])) & 0xFFFFFFFF
        a, b, c, d = ((aa + a) & 0xFFFFFFFF, (bb + b) & 0xFFFFFFFF,
                      (cc + c) & 0xFFFFFFFF, (dd + d) & 0xFFFFFFFF)
    return struct.pack("<4I", a, b, c, d).hex()


def _sha1(msg: bytes, iv: tuple[int, ...], ks: tuple[int, ...]) -> str:
    """Compact SHA-1 whose IV/round constants come from the module."""
    ml = len(msg) * 8
    msg = msg + b"\x80"
    while len(msg) % 64 != 56:
        msg += b"\x00"
    msg += struct.pack(">Q", ml)
    h = list(iv)
    for off in range(0, len(msg), 64):
        w = list(struct.unpack(">16I", msg[off:off + 64]))
        for i in range(16, 80):
            w.append(_rotl(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1))
        a, b, c, d, e = h
        for i in range(80):
            if i < 20:
                f, k = (b & c) | (~b & d), ks[0]
            elif i < 40:
                f, k = b ^ c ^ d, ks[1]
            elif i < 60:
                f, k = (b & c) | (b & d) | (c & d), ks[2]
            else:
                f, k = b ^ c ^ d, ks[3]
            f = (f & 0xFFFFFFFF)
            a, b, c, d, e = ((_rotl(a, 5) + f + e + k + w[i]) & 0xFFFFFFFF,
                             a, _rotl(b, 30), c, d)
        h = [(x + y) & 0xFFFFFFFF for x, y in zip(h, [a, b, c, d, e])]
    return "".join(f"{x:08x}" for x in h)


def _sha256(msg: bytes, iv: tuple[int, ...], ks: tuple[int, ...]) -> str:
    """Compact SHA-256 whose IV/round constants come from the module."""
    ml = len(msg) * 8
    msg = msg + b"\x80"
    while len(msg) % 64 != 56:
        msg += b"\x00"
    msg += struct.pack(">Q", ml)
    h = list(iv)
    for off in range(0, len(msg), 64):
        w = list(struct.unpack(">16I", msg[off:off + 64]))
        for i in range(16, 64):
            s0 = _rotr(w[i - 15], 7) ^ _rotr(w[i - 15], 18) ^ (w[i - 15] >> 3)
            s1 = _rotr(w[i - 2], 17) ^ _rotr(w[i - 2], 19) ^ (w[i - 2] >> 10)
            w.append((w[i - 16] + s0 + w[i - 7] + s1) & 0xFFFFFFFF)
        a, b, c, d, e, f, g, hh = h
        for i in range(64):
            S1 = _rotr(e, 6) ^ _rotr(e, 11) ^ _rotr(e, 25)
            ch = (e & f) ^ (~e & g)
            t1 = (hh + S1 + ch + ks[i] + w[i]) & 0xFFFFFFFF
            S0 = _rotr(a, 2) ^ _rotr(a, 13) ^ _rotr(a, 22)
            maj = (a & b) ^ (a & c) ^ (b & c)
            t2 = (S0 + maj) & 0xFFFFFFFF
            hh, g, f, e = g, f, e, (d + t1) & 0xFFFFFFFF
            d, c, b, a = c, b, a, (t1 + t2) & 0xFFFFFFFF
        h = [(x + y) & 0xFFFFFFFF
             for x, y in zip(h, [a, b, c, d, e, f, g, hh])]
    return "".join(f"{x:08x}" for x in h)


def _sm3(msg: bytes, iv: tuple[int, ...], ts: tuple[int, ...]) -> str:
    """Compact SM3 whose IV/T constants come from the module.

    SM3's feed-forward is XOR (not SHA-2's addition) and W'[j] =
    W[j] ^ W[j+4] over the 68-word expansion."""

    def p0(x): return x ^ _rotl(x, 9) ^ _rotl(x, 17)

    def p1(x): return x ^ _rotl(x, 15) ^ _rotl(x, 23)

    ml = len(msg) * 8
    msg = msg + b"\x80"
    while len(msg) % 64 != 56:
        msg += b"\x00"
    msg += struct.pack(">Q", ml)
    h = list(iv)
    ts64 = [ts[0]] * 16 + [ts[1]] * 48
    for off in range(0, len(msg), 64):
        w = list(struct.unpack(">16I", msg[off:off + 64]))
        for j in range(16, 68):
            w.append(p1(w[j - 16] ^ w[j - 9] ^ _rotl(w[j - 3], 15))
                     ^ _rotl(w[j - 13], 7) ^ w[j - 6])
        a, b, c, d, e, f, g, hh = h
        for j in range(64):
            wp = w[j] ^ w[j + 4]
            ss1 = _rotl((_rotl(a, 12) + e + _rotl(ts64[j], j % 32))
                        & 0xFFFFFFFF, 7)
            ss2 = ss1 ^ _rotl(a, 12)
            if j < 16:
                ff, gg = a ^ b ^ c, e ^ f ^ g
            else:
                ff = (a & b) | (a & c) | (b & c)
                gg = (e & f) | (~e & g)
            tt1 = (ff + d + ss2 + wp) & 0xFFFFFFFF
            tt2 = (gg + hh + ss1 + w[j]) & 0xFFFFFFFF
            d, c, b, a = c, _rotl(b, 9), a, tt1
            hh, g, f, e = g, _rotl(f, 19), e, p0(tt2)
        h = [x ^ y for x, y in zip(h, [a, b, c, d, e, f, g, hh])]
    return "".join(f"{x:08x}" for x in h)


_VECTORS = (b"", b"abc", b"a" * 200, bytes(range(256)))


def test_md5_table_reproduces_hashlib():
    words = constants_ref.reference_words("md5")
    digest = lambda m: _md5(m, tuple(words[:4]), tuple(words[4:]))  # noqa: E731
    for msg in _VECTORS:
        assert digest(msg) == hashlib.md5(msg).hexdigest()


def test_sha1_table_reproduces_hashlib_all_five_iv_registers():
    words = constants_ref.reference_words("sha1")
    assert len(words[:5]) == 5  # the FIPS 180-4 IV is FIVE registers
    digest = lambda m: _sha1(m, tuple(words[:5]), tuple(words[5:]))  # noqa: E731
    for msg in _VECTORS:
        assert digest(msg) == hashlib.sha1(msg).hexdigest()


def test_sha256_table_reproduces_hashlib():
    words = constants_ref.reference_words("sha256")
    digest = lambda m: _sha256(m, tuple(words[:8]), tuple(words[8:]))  # noqa: E731
    for msg in _VECTORS:
        assert digest(msg) == hashlib.sha256(msg).hexdigest()


def test_sm3_table_reproduces_published_kat():
    words = constants_ref.reference_words("sm3")
    # GB/T 32905 published known-answer vector for "abc":
    kat = ("66c7f0f462eeedd9d1f2d46bdc10e4e2"
           "4167c4875cf2f7a2297da02b8f4ba8e0")
    assert _sm3(b"abc", tuple(words[:8]), tuple(words[8:])) == kat
    if "sm3" in hashlib.algorithms_available:  # local OpenSSL extra
        for msg in _VECTORS:
            assert _sm3(msg, tuple(words[:8]),
                        tuple(words[8:])) == hashlib.new(
                            "sm3", msg).hexdigest()


def test_sha1_word_set_classifies_exact():
    """Regression pin: the FIVE-register SHA-1 table classifies as the
    exact reference (a truncated IV used to leave the fifth word
    'extra' and flipped ``exact`` to False on a genuine table)."""
    got = constants_ref.classify(set(constants_ref.reference_words("sha1")))
    assert got == {"family": "sha1", "exact": True,
                   "missing": [], "extra": []}
