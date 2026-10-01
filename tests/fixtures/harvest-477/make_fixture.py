#!/usr/bin/env python3
"""make_fixture.py — construct the script-harvest fixture substrate.

Builds the synthetic anchored sample the harvest fixture stages:
512 bytes with a 16-byte known header (magic + version + reserved
zeros), a declared little-endian length, and a deterministic payload.
Zero real-sample bytes: everything here is synthetic and generated.

The fixture CANDIDATES are committed as source (byte_digest.py —
deterministic, verifiable; byte_noise.py — nondeterministic by
construction, fails the byte-exact pin), and fact-F007.md is the
PROVEN fact whose provenance cites scripts/byte_digest.py — the
success-trace discriminator's input.

Usage:
  python make_fixture.py <outdir>      # writes sample.blob + expected.json
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

MAGIC = b"KLG1"
VERSION = 7
TOTAL = 512


def build_sample() -> bytes:
    buf = bytearray()
    buf += MAGIC
    buf += VERSION.to_bytes(2, "little")
    buf += b"\x00" * 10                      # reserved: known zeros
    buf += TOTAL.to_bytes(4, "little")       # declared length
    buf += b"payload:" + bytes(range(256)) + b":end"
    buf += b"\x00" * (TOTAL - len(buf))
    return bytes(buf)


def main(argv: list) -> int:
    outdir = Path(argv[1]) if len(argv) > 1 else Path(".")
    outdir.mkdir(parents=True, exist_ok=True)
    sample = build_sample()
    (outdir / "sample.blob").write_bytes(sample)
    expected = {
        "magic": MAGIC.decode("ascii"),
        "version": VERSION,
        "length": TOTAL,
        "sample_sha256": hashlib.sha256(sample).hexdigest(),
        "candidate_stdout": "digest=" + hashlib.sha256(sample).hexdigest(),
    }
    (outdir / "expected.json").write_text(
        json.dumps(expected, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    print(json.dumps(expected, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
