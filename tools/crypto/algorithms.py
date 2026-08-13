#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/crypto/algorithms.py — 8-algorithm pure-function crypto library.

Issue #285: consolidate the hand-copied crypto snippets that appear 15+ times
across the malware-analysis workspaces (read-only sample trees) into one
dependency-free, sample-agnostic library.

Contract for every public transform:
  * bytes in -> bytes out (pure functions; no I/O, no globals)
  * no sample hardcoding — every offset / key / nonce / size / path is a
    parameter
  * each algorithm carries a roundtrip or known-vector self-check (see
    ``self_check()``); stream ciphers round-trip via their inverse function,
    decompressors use hand-built known vectors.

Only the Python standard library is imported (struct, hashlib, lzma).

Algorithms and their source-algorithm provenance (workspace-relative script
basenames under the malware-analysis workspaces):

  1. ``chacha_block`` / ``chacha20_xor``  ChaCha20 stream cipher.
       RFC schedule (rot 16/20/24/25):  re/chacha_decrypt_at.py,
         re/chacha20.py, re/chacha20_fixed.py
       non-RFC schedule (rot 16/12/8/7): re/c313_chacha_decrypt.py
         -> kept as ``variant="non-rfc"``.
       Verified against RFC 8439 A.1 test vector #1 (all-zero key/nonce,
       counter 0 -> first block 76b8e0ad...) and RFC 8439 sec 2.3.2
       (key 000102..1f, nonce 000000090000004a00000000, counter 1 ->
       10f1e7e4...).  Both reproduce byte-exact from the source routines.
  2. ``xor_add_stream`` / ``xor_add_inverse``  XOR/ADD self-syncing stream,
       processed backward (analysis/decrypt_stage2.py).  ``xor_add_stream``
       is the sample's decrypt direction; ``xor_add_inverse`` is its true
       inverse (the source's "self-inverse" comment is mistaken — state feeds
       on the pre-XOR byte).
  3. ``rolling_xor`` / ``rolling_xor_inverse``  32-bit-state rolling XOR
       (analysis/build_crypto_decryption_evidence.py stage3, seed 0x963239fd).
       ``rolling_xor`` is the sample's decrypt direction; ``rolling_xor_inverse``
       is its true inverse (state feeds pre-XOR vs post-XOR byte).
  4. ``lzss_decompress``                 bit-level LZ decompressor.
       variant="py": decompress_stage3_py.py (exact output size).
       variant="dll": decompress_stage3_dll.py (dst-capacity bound).
  5. ``lzma_raw_decompress``             raw LZMA1 with custom filters
       (dict_size/lc/lp/pb).  analysis/decompress_vdi_aza_lzma.py.
  6. ``rsa_*``                           RSA-envelope unpadding (PKCS#1 v1.5
       type 1/2 + OAEP-SHA1/SHA256 with MGF1).  runs/c001_decrypt.py (9
       copies deduplicated).  Modulus/exponent are parameters — no key file.
  7. ``go_byte_transform``               custom keyed byte transform (Go
       sample, forward = runtime decrypt direction).  re/blob_decrypt.py.
  8. ``va_to_off``                       generic PE VA -> file offset via the
       section table (PE32/PE32+).  re/chacha_decrypt_at.py.
"""

from __future__ import annotations

import hashlib
import lzma
import struct

# ===========================================================================
# 1. ChaCha20 (RFC 8439 schedule + non-RFC variant)
# ===========================================================================

_M32 = 0xFFFFFFFF

# RFC 8439 quarter-round rotation amounts (rotr 16/20/24/25).
_RFC_QR_ROTS = (16, 20, 24, 25)
# Sample variant used by the inner-PE string cipher (rotr 16/12/8/7).
_NONRFC_QR_ROTS = (16, 12, 8, 7)

#: "expand 32-byte k"
_CHACHA_CONSTANTS = (0x61707865, 0x3320646E, 0x79622D32, 0x6B206574)


def _rotr32(x, n):
    return ((x >> n) | (x << (32 - n))) & _M32


def _qr(x, a, b, c, d, r1, r2, r3, r4):
    x[a] = (x[a] + x[b]) & _M32
    x[d] = _rotr32(x[d] ^ x[a], r1)
    x[c] = (x[c] + x[d]) & _M32
    x[b] = _rotr32(x[b] ^ x[c], r2)
    x[a] = (x[a] + x[b]) & _M32
    x[d] = _rotr32(x[d] ^ x[a], r3)
    x[c] = (x[c] + x[d]) & _M32
    x[b] = _rotr32(x[b] ^ x[c], r4)


def chacha_block(key, nonce, counter, variant="rfc"):
    """Compute one 64-byte ChaCha20 keystream block.

    key: 32 bytes.  nonce: 12 bytes.  counter: u32 block counter.
    variant: "rfc" (rot 16/20/24/25) or "non-rfc" (rot 16/12/8/7).
    """
    if len(key) != 32:
        raise ValueError("ChaCha20 key must be 32 bytes (got %d)" % len(key))
    if len(nonce) != 12:
        raise ValueError("ChaCha20 nonce must be 12 bytes (got %d)" % len(nonce))
    if variant == "rfc":
        rots = _RFC_QR_ROTS
    elif variant == "non-rfc":
        rots = _NONRFC_QR_ROTS
    else:
        raise ValueError("unknown chacha variant %r (rfc|non-rfc)" % variant)
    k = list(struct.unpack("<8I", key))
    n = list(struct.unpack("<3I", nonce))
    state = list(_CHACHA_CONSTANTS) + k + [counter & _M32] + n
    x = state[:]
    r1, r2, r3, r4 = rots
    for _ in range(10):
        _qr(x, 0, 4, 8, 12, r1, r2, r3, r4)
        _qr(x, 1, 5, 9, 13, r1, r2, r3, r4)
        _qr(x, 2, 6, 10, 14, r1, r2, r3, r4)
        _qr(x, 3, 7, 11, 15, r1, r2, r3, r4)
        _qr(x, 0, 5, 10, 15, r1, r2, r3, r4)
        _qr(x, 1, 6, 11, 12, r1, r2, r3, r4)
        _qr(x, 2, 7, 8, 13, r1, r2, r3, r4)
        _qr(x, 3, 4, 9, 14, r1, r2, r3, r4)
    return b"".join(struct.pack("<I", (x[i] + state[i]) & _M32) for i in range(16))


def chacha20_xor(data, key, nonce, counter=0, variant="rfc"):
    """XOR ``data`` with the ChaCha20 keystream (self-inverse: decrypt == encrypt).

    Keystream blocks start at ``counter`` and increment per 64-byte block.
    """
    nblocks = (len(data) + 63) // 64
    ks = b"".join(chacha_block(key, nonce, counter + i, variant) for i in range(nblocks))
    return bytes(d ^ k for d, k in zip(data, ks))


# ===========================================================================
# 2. XOR/ADD self-syncing stream (backward, self-inverse)
# ===========================================================================

def xor_add_stream(data, key=1):
    """XOR/ADD self-syncing stream, processed backward (decrypt_stage2.py).

    Walk i = len-1 .. 0: b[i] ^= key; key = (key + b[i]) & 0xFF.
    NOTE: this is the *decrypt* direction used by the sample.  It is NOT
    self-inverse (verify_decrypt.py's "self-inverse" comment is mistaken);
    the inverse is ``xor_add_inverse``, which feeds the *pre-XOR* byte into
    the state update.
    """
    out = bytearray(data)
    r15b = key & 0xFF
    for i in range(len(out) - 1, -1, -1):
        out[i] ^= r15b
        r15b = (r15b + out[i]) & 0xFF
    return bytes(out)


def xor_add_inverse(data, key=1):
    """Inverse of ``xor_add_stream`` (the "encrypt" direction).

    Walk i = len-1 .. 0: out[i] = data[i] ^ key; key = (key + data[i]) & 0xFF.
    xor_add_stream(xor_add_inverse(x)) == xor_add_inverse(xor_add_stream(x)) == x.
    """
    out = bytearray(len(data))
    r15b = key & 0xFF
    for i in range(len(out) - 1, -1, -1):
        out[i] = data[i] ^ r15b
        r15b = (r15b + data[i]) & 0xFF
    return bytes(out)


# ===========================================================================
# 3. Rolling XOR (32-bit state)
# ===========================================================================

def rolling_xor(data, seed=0x963239FD):
    """32-bit-state rolling XOR (build_crypto_decryption_evidence.py stage3).

    This is the sample's *decrypt* direction: the state is fed with the
    pre-XOR (input) byte.  It is NOT self-inverse — use ``rolling_xor_inverse``
    to encrypt (feed the output byte).
    """
    state = seed & 0xFFFFFFFF
    out = bytearray(len(data))
    for i, byte in enumerate(data):
        ks = (state >> ((i % 4) * 8)) & 0xFF
        out[i] = byte ^ ks
        state = ((state << 8) | byte) & 0xFFFFFFFF
    return bytes(out)


def rolling_xor_inverse(data, seed=0x963239FD):
    """Inverse of ``rolling_xor`` (the "encrypt" direction).

    Identical except the state is fed with the post-XOR (output) byte:
    rolling_xor(rolling_xor_inverse(x)) == rolling_xor_inverse(rolling_xor(x)) == x.
    """
    state = seed & 0xFFFFFFFF
    out = bytearray(len(data))
    for i, byte in enumerate(data):
        ks = (state >> ((i % 4) * 8)) & 0xFF
        out[i] = byte ^ ks
        state = ((state << 8) | out[i]) & 0xFFFFFFFF
    return bytes(out)


# ===========================================================================
# 4. LZSS / LZ77 bit-level decompressor (two ported variants)
# ===========================================================================

def _lzss_decompress_py(data, expected_size):
    """decompress_stage3_py.py — exact expected output size, MSB-first bits.

    Three coding paths: 00 literal / 01 short match / 10 long match /
    11 4-bit length + offset (see source docstring for the exact split).
    ``data`` is the compressed stream; trailing slack of >= 8 bytes is
    tolerated (matches the source's ``inp_pos < len(data) - 8`` guard).
    """
    if len(data) < 1:
        return b""
    out = bytearray(expected_size)
    out_pos = 1
    bit_buf, bits_left = 0, 0
    inp_pos = 1
    out[0] = data[0]

    def rdbit():
        nonlocal bit_buf, bits_left, inp_pos
        if bits_left == 0:
            if inp_pos >= len(data):
                return 0
            bit_buf = data[inp_pos]
            inp_pos += 1
            bits_left = 8
        b = (bit_buf >> 7) & 1
        bit_buf = (bit_buf << 1) & 0xFF
        bits_left -= 1
        return b

    while out_pos < expected_size and inp_pos < len(data) - 8:
        flag = rdbit()
        if flag == 0:
            flag2 = rdbit()
            if flag2 == 0:  # short match
                length = rdbit() * 2 + rdbit()
                if length == 0:
                    out[out_pos] = data[inp_pos] if inp_pos < len(data) else 0
                    inp_pos += 1
                    out_pos += 1
                else:
                    length += 1
                    offset = data[inp_pos] if inp_pos < len(data) else 0
                    inp_pos += 1
                    src = out_pos - offset
                    for _ in range(length):
                        out[out_pos] = out[src]
                        out_pos += 1
                        src += 1
                        if out_pos >= expected_size:
                            break
            else:  # long match
                length = sum((rdbit() << (3 - i)) for i in range(4))
                offset = data[inp_pos] if inp_pos < len(data) else 0
                inp_pos += 1
                if length == 0:
                    out[out_pos] = offset
                    out_pos += 1
                else:
                    src = out_pos - offset
                    for _ in range(length + 1):
                        out[out_pos] = out[src]
                        out_pos += 1
                        src += 1
                        if out_pos >= expected_size:
                            break
        else:  # copy
            flag2 = rdbit()
            if flag2 == 0:
                out[out_pos] = data[inp_pos] if inp_pos < len(data) else 0
                inp_pos += 1
                out_pos += 1
            else:
                length = sum((rdbit() << (3 - i)) for i in range(4))
                offset = data[inp_pos] if inp_pos < len(data) else 0
                inp_pos += 1
                if length == 0:
                    out[out_pos] = offset
                    out_pos += 1
                else:
                    src = out_pos - offset
                    for _ in range(length + 1):
                        out[out_pos] = out[src]
                        out_pos += 1
                        src += 1
                        if out_pos >= expected_size:
                            break

    return bytes(out)


def _lz77_decompress_dll(data, dst_size):
    """decompress_stage3_dll.py — LZ77 ported from x64 asm, dst-capacity bound.

    ``dst_size`` is the output buffer capacity; the first ``dst_size`` output
    bytes are returned (the source preallocates a dst_size buffer).  A
    top-of-loop capacity guard is added so truncated/malformed streams cannot
    spin forever; for well-formed streams the returned bytes are identical to
    the source's output.
    """
    if len(data) < 2:
        return b""
    dst = bytearray(dst_size)
    dst[0] = data[0]
    dst_pos = 1
    bit_count = 7
    bit_buf = data[1] if len(data) > 1 else 0
    src_pos = 2
    edi = 0
    ebx = 0xFFFFFFFF
    r11 = 0

    def need_bit():
        nonlocal bit_count, bit_buf, src_pos
        if bit_count < 0:
            if src_pos >= len(data):
                return 0
            bit_buf = data[src_pos]
            src_pos += 1
            bit_count = 7
        result = (bit_buf >> bit_count) & 1
        bit_count -= 1
        return result

    def read_byte():
        nonlocal src_pos
        if src_pos >= len(data):
            return 0
        b = data[src_pos]
        src_pos += 1
        return b

    def write_byte(b):
        nonlocal dst_pos
        if dst_pos < len(dst):
            dst[dst_pos] = b & 0xFF
        dst_pos += 1

    while True:
        if dst_pos >= len(dst):
            break  # capacity guard (prevents unbounded spin on malformed input)
        b1 = need_bit()
        if b1 == 0:
            bite = 0
            for _ in range(8):
                bite = (bite << 1) | need_bit()
            write_byte(bite)
            if edi:
                break
            continue

        b2 = need_bit()
        if b2 == 0:
            val = 1
            while True:
                b2a = need_bit()
                b2b = need_bit()
                val = val * 2 + b2b
                if b2a == 0:
                    break
            if r11:
                if val == 2:
                    elen = 1
                    while True:
                        b2e1 = need_bit()
                        b2e2 = need_bit()
                        elen = elen * 2 + b2e2
                        if b2e1 == 0:
                            break
                    for _ in range(elen):
                        write_byte(dst[dst_pos - ebx])
                else:
                    ebx = val - 3
                    if src_pos >= len(data):
                        break
                    hi_byte = read_byte()
                    ebx = (ebx << 8) | hi_byte
                    elen = 1
                    while True:
                        if bit_count < 0 and src_pos < len(data):
                            bit_buf = data[src_pos]
                            src_pos += 1
                            bit_count = 7
                        b3a = need_bit()
                        if bit_count < 0 and src_pos < len(data):
                            bit_buf = data[src_pos]
                            src_pos += 1
                            bit_count = 7
                        b3b = need_bit()
                        elen = elen * 2 + b3b
                        if b3a == 0:
                            break
                    if ebx >= 0x7D00:
                        elen += 1
                    if ebx >= 0x500:
                        elen += 1
                    if ebx < 0x80:
                        elen += 2
                    for _ in range(elen):
                        idx = dst_pos - ebx
                        if 0 <= idx < dst_pos:
                            write_byte(dst[idx])
                        else:
                            write_byte(0)
            else:
                ebx = val - 2
                if src_pos >= len(data):
                    break
                hi_byte = read_byte()
                ebx = (ebx << 8) | hi_byte
                elen = 1
                while True:
                    if bit_count < 0 and src_pos < len(data):
                        bit_buf = data[src_pos]
                        src_pos += 1
                        bit_count = 7
                    b3a = need_bit()
                    if bit_count < 0 and src_pos < len(data):
                        bit_buf = data[src_pos]
                        src_pos += 1
                        bit_count = 7
                    b3b = need_bit()
                    elen = elen * 2 + b3b
                    if b3a == 0:
                        break
                if ebx >= 0x7D00:
                    elen += 1
                if ebx >= 0x500:
                    elen += 1
                if ebx < 0x80:
                    elen += 2
                for _ in range(elen):
                    idx = dst_pos - ebx
                    if 0 <= idx < dst_pos:
                        write_byte(dst[idx])
                    else:
                        write_byte(0)
            r11 = 1
            if edi:
                break
        else:
            edx = 0
            for _ in range(4):
                edx = (edx << 1) | need_bit()
            if edx == 0:
                write_byte(0)
            else:
                src_idx = dst_pos - edx
                if 0 <= src_idx < dst_pos:
                    write_byte(dst[src_idx])
                else:
                    write_byte(0)
            r11 = 1
            if edi:
                break

        if src_pos >= len(data) and bit_count < 0:
            break

    return bytes(dst[:dst_pos])


def lzss_decompress(data, size, variant="py"):
    """Bit-level LZ decompressor.

    variant="py":  exact expected output size (decompress_stage3_py.py).
    variant="dll": output buffer capacity; returns the first ``size`` output
        bytes (decompress_stage3_dll.py).
    Decompress-only — the self-check is a hand-built known vector.
    """
    if variant == "py":
        return _lzss_decompress_py(data, size)
    if variant == "dll":
        return _lz77_decompress_dll(data, size)
    raise ValueError("unknown lzss variant %r (py|dll)" % variant)


# ===========================================================================
# 5. LZMA-raw decompressor (custom filters)
# ===========================================================================

def lzma_raw_decompress(data, dict_size=0x800000, lc=3, lp=0, pb=2, size=None):
    """Decompress a raw LZMA1 stream with custom filter properties.

    Filters mirror decompress_vdi_aza_lzma.py:
      dict_size (default 0x800000), lc (default 3), lp (default 0),
      pb (default 2).
    ``size`` optionally caps the output (streams without an end marker are
    decompressed until ``size`` bytes are produced).
    """
    filters = [{"id": lzma.FILTER_LZMA1, "dict_size": dict_size, "lc": lc, "lp": lp, "pb": pb}]
    dec = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=filters)
    if size is None:
        return dec.decompress(data)
    out = bytearray()
    remaining = data
    while len(out) < size:
        chunk = dec.decompress(remaining, max_length=min(0x20000, size - len(out)))
        remaining = b""
        if not chunk:
            break
        out.extend(chunk)
    return bytes(out)


# ===========================================================================
# 6. RSA-envelope unpadding (PKCS#1 v1.5 + OAEP-SHA1/SHA256)
# ===========================================================================

def rsa_raw_public(block, n, e, key_size=None):
    """Raw RSA public operation m = c^e mod n (no padding logic).

    ``key_size`` is the key bit length; when omitted it is derived from the
    modulus bit length.  The output is ``(key_size + 7) // 8`` bytes.
    """
    if key_size is None:
        key_size = n.bit_length()
    size = (key_size + 7) // 8
    return pow(int.from_bytes(block, "big"), e, n).to_bytes(size, "big")


def rsa_unpad_pkcs1v15(raw):
    """Strip PKCS#1 v1.5 padding; accept type 1 (0x01) and type 2 (0x02).

    Returns the message bytes, or None when the block is not valid padding.
    """
    if len(raw) < 11 or raw[0] != 0x00:
        return None
    btype = raw[1]
    if btype not in (0x01, 0x02):
        return None
    sep = raw.find(b"\x00", 2)
    if sep < 0 or sep < 2 + 8:  # minimum 8 bytes of PS
        return None
    if btype == 0x02 and any(b == 0 for b in raw[2:sep]):
        return None
    return raw[sep + 1:]


def mgf1(seed, length, hash_name="sha256"):
    """MGF1 mask generation function (RFC 8017). hash_name: sha1|sha256."""
    hlen = hashlib.new(hash_name).digest_size
    out = b""
    counter = 0
    while len(out) < length:
        h = hashlib.new(hash_name)
        h.update(seed + counter.to_bytes(4, "big"))
        out += h.digest()
        counter += 1
    return out[:length]


def _oaep_hash_len(hash_name):
    return hashlib.new(hash_name).digest_size


def rsa_unpad_oaep(raw, key_size, hash_name="sha256"):
    """Minimal OAEP unpadding (RFC 8017). hash_name: sha1|sha256.

    Returns the message bytes, or None when the block is not valid OAEP.
    """
    hlen = _oaep_hash_len(hash_name)
    k = key_size
    if len(raw) != k or raw[0] != 0x00:
        return None
    masked_seed = raw[1:1 + hlen]
    masked_db = raw[1 + hlen:]
    seed_mask = mgf1(masked_db, hlen, hash_name)
    seed = bytes(x ^ y for x, y in zip(masked_seed, seed_mask))
    db_mask = mgf1(seed, len(masked_db), hash_name)
    db = bytes(x ^ y for x, y in zip(masked_db, db_mask))
    lhash = hashlib.new(hash_name, b"").digest()
    if db[:hlen] != lhash:
        return None
    rest = db[hlen:]
    sep = rest.find(b"\x01")
    if sep < 0 or any(b != 0 for b in rest[:sep]):
        return None
    return rest[sep + 1:]


def rsa_envelope_decrypt(ciphertext, n, e, key_size, mode, hash_name="sha256"):
    """Decrypt an RSA envelope block-by-block with manual padding validation.

    mode: "PKCS1v15" | "OAEP-SHA1" | "OAEP-SHA256".
    Returns {"status": "OK", "plaintext": bytes, "mode": mode, "n_blocks": n}
    or {"status": "FAIL", "fail_at_block": i, "error": str,
        "raw_first8_hex": hex} — a FAIL is a *negative finding*, not an error.
    """
    block_size = (key_size + 7) // 8
    blocks = [ciphertext[i:i + block_size] for i in range(0, len(ciphertext), block_size)]
    parts = []
    for i, blk in enumerate(blocks):
        if len(blk) != block_size:
            return {"status": "FAIL", "fail_at_block": i, "error": "short block"}
        raw = rsa_raw_public(blk, n, e, key_size)
        if mode == "PKCS1v15":
            msg = rsa_unpad_pkcs1v15(raw)
        elif mode == "OAEP-SHA1":
            msg = rsa_unpad_oaep(raw, block_size, "sha1")
        elif mode == "OAEP-SHA256":
            msg = rsa_unpad_oaep(raw, block_size, "sha256")
        else:
            raise ValueError("unknown rsa mode %r (PKCS1v15|OAEP-SHA1|OAEP-SHA256)" % mode)
        if msg is None:
            return {"status": "FAIL", "fail_at_block": i,
                    "error": "padding check failed", "raw_first8_hex": raw[:8].hex()}
        parts.append(msg)
    return {"status": "OK", "plaintext": b"".join(parts), "mode": mode,
            "n_blocks": len(parts)}


# ===========================================================================
# 7. Go-sample byte transform (forward/inverse)
# ===========================================================================

# Ghidra magic-number division constant (divisor 0x61 = 97) from blob_decrypt.py.
_GO_MAGIC = -0x5717C0A8E83F5717
_GO_M64 = (1 << 64) - 1


def _s8(x):
    """Signed 8-bit of an int (C 'char' cast semantics)."""
    x &= 0xFF
    return x - 256 if x >= 0x80 else x


def _b8(x):
    """Byte truncation (assignment to uint8)."""
    return x & 0xFF


def _go_key_constants(key):
    """Precompute key-dependent byte masks per the decompiled transform."""
    # loop1 even: A = (char)key + (char)(key / 0x35) * -0x35
    A = _s8(key) + _s8(key // 0x35) * (-0x35)
    # loop1 odd: magic division by 0x61 (97): hi = high64(magic*key)
    prod = _GO_MAGIC * key
    hi_u = (prod >> 64) & _GO_M64
    hi_s = hi_u - (1 << 64) if hi_u >= (1 << 63) else hi_u
    t = hi_s + key
    d = _s8((t >> 6) & 0xFF) - _s8((key >> 0x3F) & 0xFF)  # key > 0: 2nd term = 0
    Y = _s8(key) + d * (-0x61)
    # loop2: sub = (char)((uint)key >> 8); loop3: xorkey = (byte)key
    sub2 = _s8((key >> 8) & 0xFF)
    xorkey = key & 0xFF
    return A, Y, sub2, xorkey


def _go_loop1_fwd(b, A, Y):
    n = len(b)
    for i in range(n):
        if (i & 1) == 0:
            B = _s8(i & 0xFF) * (-0x11)
            b[i] = _b8(b[i] - A + B)
        else:
            X = _s8((i << 5) & 0xFF) - _s8(i & 0xFF)
            b[i] = _b8(b[i] ^ X ^ Y)


def _go_loop1_inv(b, A, Y):
    n = len(b)
    for i in range(n):
        if (i & 1) == 0:
            B = _s8(i & 0xFF) * (-0x11)
            b[i] = _b8(b[i] + A - B)
        else:
            X = _s8((i << 5) & 0xFF) - _s8(i & 0xFF)
            b[i] = _b8(b[i] ^ X ^ Y)


def _go_forward(buf, key):
    A, Y, sub2, xorkey = _go_key_constants(key)
    b = bytearray(buf)
    n = len(b)
    _go_loop1_fwd(b, A, Y)
    for i in range(n // 2):  # reversal
        j = n - 1 - i
        b[i], b[j] = b[j], b[i]
    for i in range(0, n - 1, 2):  # adjacent pair swap
        b[i], b[i + 1] = b[i + 1], b[i]
    for i in range(n):  # loop2: -= (char)(key>>8)
        b[i] = _b8(b[i] - sub2)
    for i in range(n):  # loop3: ^= key ^ i
        b[i] ^= xorkey ^ (i & 0xFF)
    return bytes(b)


def _go_inverse(buf, key):
    A, Y, sub2, xorkey = _go_key_constants(key)
    b = bytearray(buf)
    n = len(b)
    for i in range(n):  # undo loop3
        b[i] ^= xorkey ^ (i & 0xFF)
    for i in range(n):  # undo loop2
        b[i] = _b8(b[i] + sub2)
    for i in range(0, n - 1, 2):  # undo pair swap
        b[i], b[i + 1] = b[i + 1], b[i]
    for i in range(n // 2):  # undo reversal
        j = n - 1 - i
        b[i], b[j] = b[j], b[i]
    _go_loop1_inv(b, A, Y)
    return bytes(b)


def go_byte_transform(buf, key, mode="inverse"):
    """Apply/undo the Go-sample byte transform (blob_decrypt.py).

    mode="forward": the runtime decryption direction (for this sample).
    mode="inverse": the encryption direction.
    inverse(forward(x)) == forward(inverse(x)) == x for any key.
    """
    if mode == "forward":
        return _go_forward(buf, key)
    if mode == "inverse":
        return _go_inverse(buf, key)
    raise ValueError("unknown go-byte-transform mode %r (forward|inverse)" % mode)


# ===========================================================================
# 8. PE VA -> file offset via the section table
# ===========================================================================

class VAMappingError(ValueError):
    """VA does not fall inside any PE section (negative finding)."""


def va_to_off(data, va):
    """Map a PE virtual address to a file offset via the section table.

    Supports PE32 (0x10b) and PE32+ (0x20b).  Raises VAMappingError when the
    VA is not covered by any section, and ValueError when ``data`` is not a
    parseable PE.
    """
    if len(data) < 0x40:
        raise ValueError("input too small to be a PE")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if pe + 6 > len(data) or data[pe:pe + 4] != b"PE\x00\x00":
        raise ValueError("PE signature not found at e_lfanew 0x%x" % pe)
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    size_opt = struct.unpack_from("<H", data, pe + 20)[0]
    opt = pe + 24
    magic = struct.unpack_from("<H", data, opt)[0]
    if magic == 0x20B:  # PE32+
        image_base = struct.unpack_from("<Q", data, opt + 24)[0]
    elif magic == 0x10B:  # PE32
        image_base = struct.unpack_from("<I", data, opt + 28)[0]
    else:
        raise ValueError("not a PE optional header (magic 0x%x)" % magic)
    sec = opt + size_opt
    rva = va - image_base
    for i in range(nsec):
        e = sec + i * 40
        vsize, vaddr, rsize, roff = struct.unpack_from("<IIII", data, e + 8)
        if vaddr <= rva < vaddr + max(vsize, rsize):
            return rva - vaddr + roff
    raise VAMappingError("VA 0x%x not in any section" % va)


# ===========================================================================
# Self-check
# ===========================================================================

# RFC 8439 A.1 test vector #1: 32-zero key, 12-zero nonce, counter 0.
RFC8439_A1_KEY = bytes(32)
RFC8439_A1_NONCE = bytes(12)
RFC8439_A1_FIRST_BLOCK = bytes.fromhex(
    "76b8e0ada0f13d90405d6ae55386bd28"
    "bdd219b8a08ded1aa836efcc8b770dc7"
    "da41597c5157488d7724e03fb8d84a37"
    "6a43b8f41518a11cc387b669b2ee6586"
)
# RFC 8439 sec 2.3.2: key 000102..1f, nonce 000000090000004a00000000, counter 1.
RFC8439_232_KEY = bytes.fromhex(
    "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"
)
RFC8439_232_NONCE = bytes.fromhex("000000090000004a00000000")
RFC8439_232_FIRST_BLOCK = bytes.fromhex(
    "10f1e7e4d13b5915500fdd1fa32071c4"
    "c7d1f4c733c068030422aa9ac3d46c4e"
    "d2826446079faa0914c2d705d98b02a2"
    "b5129cd1de164eb9cbd083e8a2503c4e"
)


def _build_mini_pe():
    """Synthetic PE32+ with one section for the va_to_off self-check."""
    e_lfanew = 0x80
    pe = 0x80
    opt = pe + 24
    size_opt = 0xF0
    sec = opt + size_opt
    buf = bytearray(sec + 40)
    struct.pack_into("<I", buf, 0x3C, e_lfanew)
    buf[pe:pe + 4] = b"PE\x00\x00"
    struct.pack_into("<H", buf, pe + 4, 0x8664)  # Machine (x64)
    struct.pack_into("<H", buf, pe + 6, 1)        # NumberOfSections
    struct.pack_into("<H", buf, pe + 20, size_opt)
    struct.pack_into("<H", buf, opt, 0x20B)       # PE32+
    struct.pack_into("<Q", buf, opt + 24, 0x400000)  # ImageBase
    struct.pack_into("<I", buf, sec + 8, 0x200)   # VirtualSize
    struct.pack_into("<I", buf, sec + 12, 0x1000) # VirtualAddress
    struct.pack_into("<I", buf, sec + 16, 0x200)  # SizeOfRawData
    struct.pack_into("<I", buf, sec + 20, 0x400)  # PointerToRawData
    return bytes(buf)


def self_check():
    """Run every algorithm's roundtrip/known-vector self-check.

    Returns {name: True} on success; raises AssertionError with the failing
    name on the first failure.
    """
    # 1. ChaCha20 — RFC 8439 vectors + roundtrips.
    assert chacha_block(RFC8439_A1_KEY, RFC8439_A1_NONCE, 0, "rfc") == RFC8439_A1_FIRST_BLOCK
    assert chacha_block(RFC8439_232_KEY, RFC8439_232_NONCE, 1, "rfc") == RFC8439_232_FIRST_BLOCK
    pt = bytes(range(256)) * 4
    for variant in ("rfc", "non-rfc"):
        key = bytes(range(32))
        nonce = bytes(range(12))
        ct = chacha20_xor(pt, key, nonce, counter=0, variant=variant)
        assert chacha20_xor(ct, key, nonce, counter=0, variant=variant) == pt
    # 2. XOR/ADD — forward/inverse roundtrip (the source's "self-inverse"
    #    claim is mistaken; xor_add_inverse is the true inverse).
    assert xor_add_inverse(xor_add_stream(pt, 1), 1) == pt
    assert xor_add_stream(xor_add_inverse(pt, 1), 1) == pt
    # 3. rolling XOR — forward/inverse roundtrip (source feeds pre-XOR byte;
    #    inverse feeds post-XOR byte).
    assert rolling_xor_inverse(rolling_xor(pt, 0x963239FD), 0x963239FD) == pt
    assert rolling_xor(rolling_xor_inverse(pt, 0x963239FD), 0x963239FD) == pt
    # 4. LZSS/LZ77 — known vectors ("ABAB" py, "AB" dll).
    assert lzss_decompress(bytes.fromhex("4182424142") + b"\x00" * 8, 4, "py") == b"ABAB"
    assert lzss_decompress(bytes.fromhex("4121"), 2, "dll") == b"AB"
    # 5. LZMA-raw — roundtrip through lzma.compress with the same filters.
    lzma_filters = [{"id": lzma.FILTER_LZMA1, "dict_size": 0x800000, "lc": 3, "lp": 0, "pb": 2}]
    lzma_data = b"lzma raw roundtrip payload" * 64
    assert lzma_raw_decompress(lzma.compress(lzma_data, format=lzma.FORMAT_RAW, filters=lzma_filters)) == lzma_data
    # 6. RSA — PKCS#1 v1.5 known block + OAEP roundtrip built via mgf1.
    msg = b"M"
    raw_pkcs = b"\x00\x02" + b"\x11" * 16 + b"\x00" + msg
    assert rsa_unpad_pkcs1v15(raw_pkcs) == msg
    hlen = 32
    k = 128
    db = hashlib.sha256(b"").digest() + b"\x00" * (k - 2 * hlen - 2 - len(msg)) + b"\x01" + msg
    seed = bytes(range(hlen))
    db_mask = mgf1(seed, k - hlen - 1, "sha256")
    masked_db = bytes(x ^ y for x, y in zip(db, db_mask))
    seed_mask = mgf1(masked_db, hlen, "sha256")
    masked_seed = bytes(x ^ y for x, y in zip(seed, seed_mask))
    raw_oaep = b"\x00" + masked_seed + masked_db
    assert rsa_unpad_oaep(raw_oaep, k, "sha256") == msg
    # 7. Go-byte-transform — inverse(forward) == forward(inverse) == id.
    for n in (1, 2, 3, 7, 8, 64, 256):
        buf = bytes((i * 7 + n) & 0xFF for i in range(n))
        assert go_byte_transform(go_byte_transform(buf, 0x17182, "forward"), 0x17182, "inverse") == buf
        assert go_byte_transform(go_byte_transform(buf, 0x17182, "inverse"), 0x17182, "forward") == buf
    # 8. va_to_off — synthetic PE32+ mapping.
    pe = _build_mini_pe()
    assert va_to_off(pe, 0x401050) == 0x450
    assert va_to_off(pe, 0x401000) == 0x400
    try:
        va_to_off(pe, 0x500000)
        raise AssertionError("va_to_off should have raised VAMappingError")
    except VAMappingError:
        pass

    names = (
        "chacha20_rfc_vectors", "chacha20_roundtrip", "xor_add_stream",
        "rolling_xor", "lzss_known_vectors", "lzma_raw_roundtrip",
        "rsa_unpad", "go_byte_transform", "va_to_off",
    )
    return {name: True for name in names}
