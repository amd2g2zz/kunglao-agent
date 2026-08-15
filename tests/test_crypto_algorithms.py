# -*- coding: utf-8 -*-
"""tests/test_crypto_algorithms.py — issue #285 crypto algorithm library unit tests.

TDD contract:
  * ChaCha20 RFC 8439 A.1 test vector #1 -> first block 76b8e0ad...
    (and RFC 8439 sec 2.3.2 -> 10f1e7e4...)
  * every algorithm roundtrips (stream ciphers via their inverse function,
    decompressors via hand-built known vectors)
"""
from __future__ import annotations

import lzma
import struct

import pytest

from crypto.algorithms import (
    VAMappingError,
    chacha20_xor,
    chacha_block,
    go_byte_transform,
    lzma_raw_decompress,
    lzss_decompress,
    mgf1,
    rolling_xor,
    rolling_xor_inverse,
    rsa_envelope_decrypt,
    rsa_unpad_oaep,
    rsa_unpad_pkcs1v15,
    self_check,
    va_to_off,
    xor_add_inverse,
    xor_add_stream,
)

# ---------------------------------------------------------------------------
# ChaCha20 — RFC 8439 test vectors
# ---------------------------------------------------------------------------

RFC8439_A1_FIRST_BLOCK = bytes.fromhex(
    "76b8e0ada0f13d90405d6ae55386bd28"
    "bdd219b8a08ded1aa836efcc8b770dc7"
    "da41597c5157488d7724e03fb8d84a37"
    "6a43b8f41518a11cc387b669b2ee6586"
)
RFC8439_232_FIRST_BLOCK = bytes.fromhex(
    "10f1e7e4d13b5915500fdd1fa32071c4"
    "c7d1f4c733c068030422aa9ac3d46c4e"
    "d2826446079faa0914c2d705d98b02a2"
    "b5129cd1de164eb9cbd083e8a2503c4e"
)


def test_chacha20_rfc8439_a1_vector_first_block():
    # RFC 8439 A.1 test vector #1: 32-zero key, 12-zero nonce, counter 0.
    block = chacha_block(bytes(32), bytes(12), 0, variant="rfc")
    assert block == RFC8439_A1_FIRST_BLOCK
    assert block[:4].hex() == "76b8e0ad"


def test_chacha20_rfc8439_232_vector():
    # RFC 8439 sec 2.3.2: key 000102..1f, nonce 000000090000004a00000000, ctr 1.
    key = bytes.fromhex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f")
    nonce = bytes.fromhex("000000090000004a00000000")
    assert chacha_block(key, nonce, 1, variant="rfc") == RFC8439_232_FIRST_BLOCK


@pytest.mark.parametrize("variant", ["rfc", "non-rfc"])
def test_chacha20_xor_roundtrip(variant):
    data = bytes(range(256)) * 4
    key = bytes(range(32))
    nonce = bytes(range(12))
    ct = chacha20_xor(data, key, nonce, counter=0, variant=variant)
    assert chacha20_xor(ct, key, nonce, counter=0, variant=variant) == data


def test_chacha20_rejects_bad_params():
    with pytest.raises(ValueError):
        chacha_block(b"\x00" * 16, bytes(12), 0)          # short key
    with pytest.raises(ValueError):
        chacha_block(bytes(32), b"\x00" * 8, 0)           # short nonce
    with pytest.raises(ValueError):
        chacha_block(bytes(32), bytes(12), 0, variant="bogus")


# ---------------------------------------------------------------------------
# XOR/ADD stream
# ---------------------------------------------------------------------------

def test_xor_add_stream_roundtrip():
    data = bytes(range(256)) * 4
    assert xor_add_inverse(xor_add_stream(data, 1), 1) == data
    assert xor_add_stream(xor_add_inverse(data, 1), 1) == data


def test_xor_add_stream_sample_direction():
    # decrypt(encrypt(x)) == x with key 1
    plain = bytes([0x41, 0x42, 0x43, 0x44])
    enc = xor_add_inverse(plain, 1)
    assert xor_add_stream(enc, 1) == plain


# ---------------------------------------------------------------------------
# Rolling XOR
# ---------------------------------------------------------------------------

def test_rolling_xor_roundtrip():
    data = bytes(range(256)) * 4
    seed = 0x963239FD
    assert rolling_xor_inverse(rolling_xor(data, seed), seed) == data
    assert rolling_xor(rolling_xor_inverse(data, seed), seed) == data


# ---------------------------------------------------------------------------
# LZSS / LZ77
# ---------------------------------------------------------------------------

def test_lzss_py_known_vector():
    # "ABAB": first literal 'A' (0x41) then copy-literal 'B',
    # short-match-literal 'A', copy-literal 'B'; source needs >=8 trailing
    # slack bytes (the len(data)-8 guard).
    comp = bytes.fromhex("4182424142") + b"\x00" * 8
    assert lzss_decompress(comp, size=4, variant="py") == b"ABAB"


def test_lzss_dll_known_vector():
    # "AB": first literal 'A', then literal 'B' (capacity guard stops at size).
    assert lzss_decompress(bytes.fromhex("4121"), size=2, variant="dll") == b"AB"


def test_lzss_invalid_variant():
    with pytest.raises(ValueError):
        lzss_decompress(b"\x41", size=1, variant="bogus")


# ---------------------------------------------------------------------------
# LZMA-raw
# ---------------------------------------------------------------------------

def test_lzma_raw_roundtrip():
    filters = [{"id": lzma.FILTER_LZMA1, "dict_size": 0x800000, "lc": 3, "lp": 0, "pb": 2}]
    data = b"lzma raw roundtrip payload" * 50
    comp = lzma.compress(data, format=lzma.FORMAT_RAW, filters=filters)
    assert lzma_raw_decompress(comp) == data


def test_lzma_raw_custom_filters_and_size():
    filters = [{"id": lzma.FILTER_LZMA1, "dict_size": 0x400000, "lc": 2, "lp": 1, "pb": 1}]
    data = b"custom filter lzma payload" * 20
    comp = lzma.compress(data, format=lzma.FORMAT_RAW, filters=filters)
    assert lzma_raw_decompress(comp, dict_size=0x400000, lc=2, lp=1, pb=1) == data


# ---------------------------------------------------------------------------
# RSA-envelope unpadding
# ---------------------------------------------------------------------------

def test_rsa_unpad_pkcs1v15_type2():
    msg = b"hello rsa"
    raw = b"\x00\x02" + b"\xAA" * 20 + b"\x00" + msg
    assert rsa_unpad_pkcs1v15(raw) == msg


def test_rsa_unpad_pkcs1v15_rejects_garbage():
    assert rsa_unpad_pkcs1v15(b"\x01\x02\x03") is None
    assert rsa_unpad_pkcs1v15(b"\x00\x02" + b"\x00" * 12) is None  # zero in PS
    assert rsa_unpad_pkcs1v15(b"\x00\x02" + b"\xAA" * 6) is None    # short PS


def test_rsa_unpad_oaep_roundtrip():
    msg = b"oaep message"
    hash_name = "sha256"
    hlen = 32
    k = 128
    db = (hashlib_sha256(b"") + b"\x00" * (k - 2 * hlen - 2 - len(msg))
          + b"\x01" + msg)
    seed = bytes(range(hlen))
    masked_db = bytes(x ^ y for x, y in zip(db, mgf1(seed, k - hlen - 1, hash_name)))
    masked_seed = bytes(x ^ y for x, y in zip(seed, mgf1(masked_db, hlen, hash_name)))
    raw = b"\x00" + masked_seed + masked_db
    assert rsa_unpad_oaep(raw, k, hash_name) == msg


def hashlib_sha256(data):
    import hashlib
    return hashlib.sha256(data).digest()


# -- small deterministic RSA keypair helpers (Miller-Rabin) ------------------

def _is_probable_prime(n):
    if n < 2:
        return False
    for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if n % p == 0:
            return n == p
    d = n - 1
    s = 0
    while d % 2 == 0:
        s += 1
        d //= 2
    for a in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if a >= n:
            continue
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(s - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _next_prime(start):
    n = start | 1
    while not _is_probable_prime(n):
        n += 2
    return n


def test_rsa_envelope_decrypt_pkcs1v15_roundtrip():
    p = _next_prime(2 ** 47 + 12345)
    q = _next_prime(2 ** 47 + 54321)
    n = p * q
    e = 65537
    phi = (p - 1) * (q - 1)
    d = pow(e, -1, phi)
    key_size = n.bit_length()
    block_size = (key_size + 7) // 8
    assert block_size >= 11  # PKCS#1 v1.5 needs room for PS

    msg = b"M"
    raw = b"\x00\x02" + b"\x11" * (block_size - 3 - len(msg)) + b"\x00" + msg
    ct = pow(int.from_bytes(raw, "big"), d, n).to_bytes(block_size, "big")

    result = rsa_envelope_decrypt(ct, n, e, key_size, "PKCS1v15")
    assert result["status"] == "OK"
    assert result["plaintext"] == msg


def test_rsa_envelope_decrypt_negative_finding():
    # A 2-byte ciphertext with a tiny modulus can never unpad (block < 11B).
    n = 101 * 103  # 10403
    result = rsa_envelope_decrypt(b"\x01\x02", n, 65537, n.bit_length(), "PKCS1v15")
    assert result["status"] == "FAIL"
    assert "fail_at_block" in result


# ---------------------------------------------------------------------------
# Go-byte-transform
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n", [1, 2, 3, 7, 8, 64, 256])
def test_go_byte_transform_roundtrip(n):
    data = bytes((i * 7 + n) & 0xFF for i in range(n))
    key = 0x17182
    assert go_byte_transform(go_byte_transform(data, key, "forward"), key, "inverse") == data
    assert go_byte_transform(go_byte_transform(data, key, "inverse"), key, "forward") == data


def test_go_byte_transform_invalid_mode():
    with pytest.raises(ValueError):
        go_byte_transform(b"\x00", 0, "bogus")


# ---------------------------------------------------------------------------
# va_to_off (PE VA -> file offset)
# ---------------------------------------------------------------------------

def _build_mini_pe(magic=0x20B, image_base=0x400000, nsec=1):
    """Synthetic PE with ``nsec`` sections, each 0x1000-aligned VA / 0x200 raw."""
    e_lfanew = 0x80
    pe = 0x80
    opt = pe + 24
    size_opt = 0xF0
    sec = opt + size_opt
    buf = bytearray(sec + 40 * nsec)
    struct.pack_into("<I", buf, 0x3C, e_lfanew)
    buf[pe:pe + 4] = b"PE\x00\x00"
    struct.pack_into("<H", buf, pe + 4, 0x8664 if magic == 0x20B else 0x14C)
    struct.pack_into("<H", buf, pe + 6, nsec)
    struct.pack_into("<H", buf, pe + 20, size_opt)
    struct.pack_into("<H", buf, opt, magic)
    if magic == 0x20B:
        struct.pack_into("<Q", buf, opt + 24, image_base)
    else:
        struct.pack_into("<I", buf, opt + 28, image_base)
    for i in range(nsec):
        e = sec + i * 40
        struct.pack_into("<I", buf, e + 8, 0x200)          # VirtualSize
        struct.pack_into("<I", buf, e + 12, 0x1000 * (i + 1))  # VirtualAddress
        struct.pack_into("<I", buf, e + 16, 0x200)         # SizeOfRawData
        struct.pack_into("<I", buf, e + 20, 0x400 + 0x200 * i)  # PointerToRawData
    return bytes(buf)


def test_va_to_off_pe32_plus():
    pe = _build_mini_pe(magic=0x20B, image_base=0x400000)
    assert va_to_off(pe, 0x401050) == 0x450
    assert va_to_off(pe, 0x401000) == 0x400
    assert va_to_off(pe, 0x4011FF) == 0x5FF


def test_va_to_off_pe32():
    pe = _build_mini_pe(magic=0x10B, image_base=0x400000)
    assert va_to_off(pe, 0x401050) == 0x450


def test_va_to_off_multiple_sections():
    pe = _build_mini_pe(magic=0x20B, image_base=0x400000, nsec=2)
    assert va_to_off(pe, 0x401050) == 0x450
    assert va_to_off(pe, 0x402123) == 0x400 + 0x200 + 0x123


def test_va_to_off_out_of_section_is_negative():
    pe = _build_mini_pe()
    with pytest.raises(VAMappingError):
        va_to_off(pe, 0x500000)


def test_va_to_off_not_a_pe():
    with pytest.raises(ValueError):
        va_to_off(b"\x00" * 64, 0x401000)


# ---------------------------------------------------------------------------
# Aggregate self-check
# ---------------------------------------------------------------------------

def test_self_check_all_ok():
    results = self_check()
    assert all(results.values()), results
