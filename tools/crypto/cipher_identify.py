#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cipher_identify.py — captured-param cipher-shape classifier.

Answers one question mechanically: given an opaque captured parameter
(sign token, cookie blob, encrypted payload), what crypto family does its
SHAPE (charset × decoded length × entropy) point at, and what should be
checked next to confirm?

This is a classifier, not a decoder. It never claims an algorithm — it
ranks family candidates with evidence and a concrete next check. Actual
decode/verify work belongs to the registered crypto decode CLI.

Input: one captured param string (positional) or --in <file> (text, one
  token). Output: stdout JSON {charset, decoded_byte_len,
  entropy_bits_per_byte, printable_ratio, candidates: [{family, confidence,
  why, next_check}]}. Exit 0 = classification produced (an empty candidate
  list for unrecognized garbage is a valid answer); exit 2 = bad tool input
  (no sample, unreadable/undecodable file, both sample and --in given).

Usage:
  python tools/crypto/cipher_identify.py "e10adc3949ba59abbe56e057f20f883e"
  python tools/crypto/cipher_identify.py --in captured_param.txt

Examples:
  # 32-hex captured token -> md5 family (high) + md4/ntlm tail
  python tools/crypto/cipher_identify.py "e10adc3949ba59abbe56e057f20f883e"

  # base64 blob of 16 aligned bytes -> aes candidate + key/iv next check
  python tools/crypto/cipher_identify.py "AAECAwQFBgcICQoLDA0ODw=="

  # classify a whole captured file (whitespace-trimmed single token)
  python tools/crypto/cipher_identify.py --in captured_param.txt
"""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import math
import re
import sys
from pathlib import Path

# UTF-8 stdout guard via the shared tools/ _lib; the guard itself fires in
# __main__ only.
import sys as _sys_io, pathlib as _pathlib_io
_TOOLS_DIR = next(_p for _p in _pathlib_io.Path(__file__).resolve().parents
                  if _p.name == "tools")
if str(_TOOLS_DIR) not in _sys_io.path:
    _sys_io.path.insert(0, str(_TOOLS_DIR))
from _lib.stdio import ensure_utf8_stdout  # noqa: E402

UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
HEX_RE = re.compile(r"^[0-9a-f]+$")
HEX_UP_RE = re.compile(r"^[0-9A-F]+$")
DECIMAL_RE = re.compile(r"^[0-9]+$")
B64_RE = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")
B64URL_RE = re.compile(r"^[A-Za-z0-9_-]+$")
ALNUM_RE = re.compile(r"^[A-Za-z0-9]+$")

PRINTABLE = set(range(0x20, 0x7F)) | {0x09, 0x0A, 0x0D}

# digest family table keyed on DECODED byte length (hex samples are 2x)
HASH_TABLE: dict[int, list[tuple[str, str, str]]] = {
    16: [("md5", "high",
          "16-byte digest is the MD5 shape",
          "hash a known input and compare; a mismatch with correct length "
          "may mean a custom/truncated MD5 variant"),
         ("md4/ntlm", "low",
          "same digest shape as MD4/NTLM",
          "test the NTLM variant (unicode-le input) if plain MD5 fails")],
    20: [("sha-1", "high",
          "20-byte digest is the SHA-1 shape",
          "hash a known input; also try SHA-1 over a concatenated "
          "timestamp+param scheme")],
    28: [("sha-224", "high",
          "28-byte digest is the SHA-224 shape",
          "hash a known input to confirm")],
    32: [("sha-256", "high",
          "32-byte digest is the SHA-256 shape",
          "hash a known input; if it mismatches, look for a secret "
          "prefix/suffix (HMAC) in the JS"),
         ("sm3", "medium",
          "SM3 digests share the 32-byte digest shape",
          "if context is a CN-origin site, try SM3 with the same input")],
    48: [("sha-384", "high",
          "48-byte digest is the SHA-384 shape",
          "hash a known input to confirm")],
    64: [("sha-512", "high",
          "64-byte digest is the SHA-512 shape",
          "hash a known input to confirm"),
         ("sha3-512", "low",
          "same digest length as SHA-512",
          "try SHA3-512 if SHA-512 mismatch")],
}

RSA_SIZES = {128: "1024", 256: "2048", 384: "3072", 512: "4096"}


def detect_charset(sample: str) -> str:
    if any(ord(ch) > 127 for ch in sample):
        return "non-ascii"
    if UUID_RE.match(sample):
        return "uuid"
    if sample.count(".") == 2:
        return "jwt-like"
    if DECIMAL_RE.match(sample):
        return "decimal"
    if HEX_RE.match(sample):
        return "hex_lower"
    if HEX_UP_RE.match(sample):
        return "hex_upper"
    if B64_RE.match(sample) and ("=" in sample or len(sample) % 4 == 0):
        return "base64"
    if B64URL_RE.match(sample):
        return "base64url"
    if ALNUM_RE.match(sample):
        return "alphanumeric"
    return "unknown"


def _b64_pad(part: str, urlsafe: bool) -> bytes:
    padded = part + "=" * (-len(part) % 4)
    if urlsafe:
        return base64.urlsafe_b64decode(padded)
    return base64.b64decode(padded)


def decode_payload(sample: str, charset: str) -> bytes | None:
    try:
        if charset == "hex_lower" or charset == "hex_upper":
            return bytes.fromhex(sample)
        if charset == "base64":
            return _b64_pad(sample, urlsafe=False)
        if charset == "base64url":
            return _b64_pad(sample, urlsafe=True)
        if charset == "jwt-like":
            parts = [_b64_pad(p, urlsafe=True) for p in sample.split(".")]
            return b"".join(parts)
    except (ValueError, binascii.Error):
        return None
    return None


def shannon_entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts: dict[int, int] = {}
    for b in data:
        counts[b] = counts.get(b, 0) + 1
    total = len(data)
    entropy = round(-sum((c / total) * math.log2(c / total)
                         for c in counts.values()), 3)
    return max(0.0, entropy)  # avoid -0.0 in the JSON contract


def printable_ratio(data: bytes | None) -> float:
    if not data:
        return 0.0
    hits = sum(1 for b in data if b in PRINTABLE)
    return round(hits / len(data), 3)


def collect_candidates(sample: str, charset: str, decoded: bytes | None,
                       entropy: float) -> list[dict]:
    cands: list[dict] = []
    n = len(decoded) if decoded is not None else 0
    is_block_input = charset in ("hex_lower", "hex_upper", "base64",
                                 "base64url", "jwt-like")

    if charset == "jwt-like":
        cands.append({
            "family": "jwt", "confidence": "high",
            "why": "three dot-separated base64url segments",
            "next_check": "base64url-decode segment 2 for the claim set; "
                          "segment 3 signs segments 1+2 — find the secret "
                          "or the signing key id in the JS"})
    if decoded is not None and printable_ratio(decoded) >= 0.85 and n > 0 \
            and charset in ("base64", "base64url"):
        cands.append({
            "family": "base64-text", "confidence": "high",
            "why": "base64 payload decodes to printable text",
            "next_check": "read the decoded text; this is an encoding, not "
                          "encryption — no key search needed"})
    if charset == "uuid":
        cands.append({
            "family": "uuid", "confidence": "high",
            "why": "canonical 8-4-4-4-12 hex layout",
            "next_check": "treat as an identifier, not crypto; check "
                          "whether it is random per-session or derived"})
    if charset == "decimal" and len(sample) in (10, 13):
        unit = "unix seconds" if len(sample) == 10 else "unix milliseconds"
        cands.append({
            "family": "unix-timestamp", "confidence": "high",
            "why": f"{len(sample)}-digit decimal reads as {unit}",
            "next_check": "compare against request time; timestamps are "
                          "often signed together with other fields"})
    if is_block_input and n in HASH_TABLE:
        for name, conf, why, nxt in HASH_TABLE[n]:
            cands.append({"family": name, "confidence": conf,
                          "why": why, "next_check": nxt})
    if is_block_input and n >= 16 and n % 16 == 0:
        conf = "high" if entropy >= 7.0 else "medium"
        cands.append({
            "family": "aes", "confidence": conf,
            "why": f"decoded length {n} is 16-aligned (AES block size)"
                   + (f"; entropy {entropy} is encryption-tight"
                      if entropy >= 7.0 else ""),
            "next_check": "locate the key (16/24/32 bytes) and mode "
                          "(ECB has no IV; CBC needs one) in the JS"})
    if is_block_input and n >= 16 and n % 16 == 0:
        cands.append({
            "family": "sm4", "confidence": "low",
            "why": "16-aligned blocks also fit SM4",
            "next_check": "if the site is CN-origin and AES fails, try SM4 "
                          "with a 16-byte key"})
    if is_block_input and n >= 8 and n % 8 == 0 and n % 16 != 0:
        cands.append({
            "family": "des-family", "confidence": "medium",
            "why": f"decoded length {n} is 8-aligned but not 16-aligned "
                   "(DES/3DES/Blowfish block size)",
            "next_check": "try 3DES with a 24-byte key, then DES (8-byte "
                          "key), then Blowfish"})
    if is_block_input and n in RSA_SIZES:
        cands.append({
            "family": "rsa-modulus", "confidence": "medium",
            "why": f"decoded length {n} matches a "
                   f"{RSA_SIZES[n]}-bit RSA operation output",
            "next_check": "find the public key in the page/JS; RSA on "
                          "request data is usually a fixed public-key "
                          "encrypt, not a sign"})
    return cands


def classify(sample: str) -> dict:
    charset = detect_charset(sample)
    decoded = decode_payload(sample, charset)
    entropy = shannon_entropy(decoded if decoded is not None
                              else sample.encode("utf-8", "replace"))
    cands = collect_candidates(sample, charset, decoded, entropy)
    return {
        "sample_len": len(sample),
        "charset": charset,
        "decoded_byte_len": len(decoded) if decoded is not None else None,
        "entropy_bits_per_byte": entropy,
        "printable_ratio": printable_ratio(decoded),
        "candidates": cands,
        "note": ("classifier only — candidates are ranked hypotheses with "
                 "next checks; perform the actual decode/verify with the "
                 "registered crypto decode CLI"),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="classify a captured param's cipher shape "
                    "(charset x length x entropy)",
        epilog=(
            "exit codes: 0 = classification produced (empty candidates for "
            "unrecognized garbage is a valid answer); 2 = bad tool input\n"
            "\n"
            "Examples:\n"
            "  # 32-hex captured token -> md5 family (high) + md4/ntlm tail\n"
            "  python tools/crypto/cipher_identify.py "
            '"e10adc3949ba59abbe56e057f20f883e"\n'
            "\n"
            "  # base64 blob of 16 aligned bytes -> aes candidate + "
            "key/iv next check\n"
            "  python tools/crypto/cipher_identify.py "
            '"AAECAwQFBgcICQoLDA0ODw=="\n'
            "\n"
            "  # classify a captured file (whitespace-trimmed single token)\n"
            "  python tools/crypto/cipher_identify.py "
            "--in captured_param.txt"),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sample", nargs="?", default=None,
                    help="captured param string (hex/base64/b64url/decimal)")
    ap.add_argument("--in", dest="in_file", default=None,
                    help="read the sample from a text file (single token)")
    args = ap.parse_args(argv)

    if args.sample is None and args.in_file is None:
        ap.error("provide a sample string or --in <file>")
    if args.sample is not None and args.in_file is not None:
        ap.error("sample and --in are mutually exclusive")

    if args.in_file is not None:
        p = Path(args.in_file)
        try:
            sample = p.read_text(encoding="utf-8").strip()
        except OSError as exc:
            print(f"cipher_identify: cannot read {p}: {exc}", file=sys.stderr)
            return 2
        except UnicodeDecodeError as exc:
            print(f"cipher_identify: {p} is not valid UTF-8 text: {exc}",
                  file=sys.stderr)
            return 2
    else:
        sample = args.sample or ""

    if not sample:
        print("cipher_identify: empty sample — nothing to classify",
              file=sys.stderr)
        return 2
    if any(ch.isspace() for ch in sample):
        print("cipher_identify: sample contains whitespace; captured params "
              "are single tokens — pass one token", file=sys.stderr)
        return 2

    print(json.dumps(classify(sample), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    ensure_utf8_stdout()
    sys.exit(main())
