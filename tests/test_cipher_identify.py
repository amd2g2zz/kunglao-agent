# -*- coding: utf-8 -*-
"""cipher_identify — captured-param cipher-shape classification pins.

Synthetic fixtures only. Each pin checks that a shape-typical captured param
string produces the expected family candidate with the expected confidence,
and that malformed tool-level input fails loudly (non-zero exit + stderr
message) instead of guessing.
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "crypto" / "cipher_identify.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True)


def _verdict(*args: str) -> dict:
    r = _run(*args)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _families(out: dict) -> list[str]:
    return [c["family"] for c in out["candidates"]]


def test_md5_hex_sample() -> None:
    out = _verdict("e10adc3949ba59abbe56e057f20f883e")
    assert out["charset"] == "hex_lower"
    assert out["decoded_byte_len"] == 16
    fams = _families(out)
    assert "md5" in fams
    top = out["candidates"][fams.index("md5")]
    assert top["confidence"] == "high"


def test_sha256_hex_sample() -> None:
    out = _verdict("ab" * 32)
    assert out["decoded_byte_len"] == 32
    fams = _families(out)
    assert "sha-256" in fams
    assert "sm3" in fams  # same 32-byte digest shape, context-dependent


def test_sha1_and_sha512_lengths() -> None:
    assert "sha-1" in _families(_verdict("ab" * 20))
    assert "sha-512" in _families(_verdict("ab" * 64))


def test_base64_of_block_aligned_binary_suggests_aes() -> None:
    payload = base64.b64encode(bytes(range(16))).decode()
    out = _verdict(payload)
    assert out["charset"] == "base64"
    assert out["decoded_byte_len"] == 16
    fams = _families(out)
    assert "aes" in fams
    aes = out["candidates"][fams.index("aes")]
    assert aes["confidence"] in ("medium", "high")


def test_8byte_block_suggests_des_family() -> None:
    payload = base64.b64encode(bytes(8)).decode()
    out = _verdict(payload)
    fams = _families(out)
    assert "des-family" in fams


def test_high_entropy_reported_for_encrypted_shape() -> None:
    payload = base64.b64encode(bytes(range(256)) * 2).decode()
    out = _verdict(payload)
    assert out["entropy_bits_per_byte"] > 7.0


def test_jwt_shape_detected() -> None:
    token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc123def"
    out = _verdict(token)
    assert "jwt" in _families(out)


def test_unix_timestamp_decimal() -> None:
    out = _verdict("1700000000")
    assert "unix-timestamp" in _families(out)


def test_uuid_shape() -> None:
    out = _verdict("550e8400-e29b-41d4-a716-446655440000")
    assert "uuid" in _families(out)


def test_plain_base64_decoding_to_text_ranks_first() -> None:
    payload = base64.b64encode("hello sign world".encode()).decode()
    out = _verdict(payload)
    top = out["candidates"][0]
    assert top["family"] == "base64-text"
    assert top["confidence"] == "high"


def test_recognized_garbage_is_an_answer_not_an_error() -> None:
    out = _verdict("你好!!@@")
    assert out["charset"] in ("unknown", "non-ascii")
    assert out["candidates"] == []


def test_empty_sample_fails_loud() -> None:
    r = _run("")
    assert r.returncode == 2
    assert r.stderr.strip()


def test_missing_file_fails_loud() -> None:
    r = _run("--in", str(ROOT / "no" / "such" / "file.txt"))
    assert r.returncode == 2
    assert r.stderr.strip()


def test_unreadable_bytes_fail_loud(tmp_path: Path) -> None:
    p = tmp_path / "bin.param"
    p.write_bytes(b"\xff\xfe\x00\x81")
    r = _run("--in", str(p))
    # undecodable text input is a loud tool error, not a silent empty verdict
    assert r.returncode == 2
    assert r.stderr.strip()


def test_help_carries_examples() -> None:
    r = _run("--help")
    assert r.returncode == 0
    assert "Examples:" in r.stdout
    assert "python tools/crypto/cipher_identify.py" in r.stdout
