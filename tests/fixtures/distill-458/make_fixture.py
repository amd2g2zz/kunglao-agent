#!/usr/bin/env python3
"""make_fixture.py — construct the unknown-format distillation fixture.

Builds the synthetic sample the online-distillation fixture e2e stages:
a tiny structured binary (a 16-byte known header: magic + version +
reserved zeros, then a declared length and a printable payload)
encrypted with a periodic-XOR + position-add transform:

    cipher[i] = ((plain[i] ^ KEY[i mod 8]) + i) & 0xFF

The transform family (periodic key stream composed with a modular
position add, forward direction) is deliberately absent from the
registered crypto toolshelf — the fixture's premise is a GENUINE
shelf miss, and the committed pin test sweeps the shelf's parameter
spaces to prove no registered algorithm recovers the plaintext.

Zero real-sample bytes: everything here is synthetic and generated.
The key never leaves this generator (the recovery method re-derives
it from the ciphertext via the known 16-byte header).

Usage:
  python make_fixture.py <outdir>      # writes sample.blob + expected.json
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

MAGIC = b"KLG1"
VERSION = 3
KEY = bytes([0x5A, 0xC3, 0x11, 0x8F, 0x2B, 0x77, 0xD4, 0x09])
TOTAL = 512


def build_plain() -> bytes:
    plain = bytearray()
    plain += MAGIC
    plain += VERSION.to_bytes(2, "little")
    plain += b"\x00" * 10                      # reserved: known zeros
    plain += TOTAL.to_bytes(4, "little")       # declared length
    plain += b"payload:" + bytes(range(256)) + b":end"
    plain += b"\x00" * (TOTAL - len(plain))
    return bytes(plain)


def encrypt(plain: bytes, key: bytes) -> bytes:
    return bytes(((plain[i] ^ key[i % len(key)]) + i) & 0xFF
                 for i in range(len(plain)))


def main(argv: list[str]) -> int:
    outdir = Path(argv[1]) if len(argv) > 1 else Path(".")
    outdir.mkdir(parents=True, exist_ok=True)
    plain = build_plain()
    cipher = encrypt(plain, KEY)
    (outdir / "sample.blob").write_bytes(cipher)
    expected = {
        "magic": MAGIC.decode("ascii"),
        "version": VERSION,
        "length": TOTAL,
        "plain_sha256": hashlib.sha256(plain).hexdigest(),
        "cipher_sha256": hashlib.sha256(cipher).hexdigest(),
    }
    (outdir / "expected.json").write_text(
        json.dumps(expected, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    print(json.dumps(expected, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
