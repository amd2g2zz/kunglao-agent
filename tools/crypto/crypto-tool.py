#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/crypto/crypto-tool.py — issue #285 crypto algorithm-library CLI.

One subcommand per algorithm over the sibling library (algorithms.py), with a
uniform I/O and reporting contract:

  --in PATH | --in-hex HEX   input bytes (file path or inline hex)
  --out PATH                 write output bytes to a file (optional)
  --json                     machine-readable JSON report on stdout
  --reproduce                print field=value lines (kunglao L1 mechanical gate)

Exit codes: 0 = success, 1 = negative finding (operation ran, no result),
2 = error (bad args / unreadable input / library error).  Errors print a
structured JSON object to stderr: {"error": "...", "exit_code": 2}.

Subcommands (each is pure / deterministic / idempotent):
  chacha              ChaCha20 XOR stream (--key, --nonce, --counter, --variant)
  xor-add             XOR/ADD self-syncing stream (--key, --mode decrypt|encrypt)
  rolling-xor         32-bit-state rolling XOR (--seed, --mode decrypt|encrypt)
  lzss                LZ decompressor (--variant py|dll, --size)
  lzma-raw            raw LZMA1 (--dict-size, --lc, --lp, --pb, --size)
  rsa-unpad           RSA-envelope unpad (--mode, --n, --e, --key-size)
  go-byte-transform   Go byte transform (--key, --mode forward|inverse)
  va-to-off           PE VA -> file offset (--va)

  --self-check        run every algorithm's roundtrip/known-vector self-check
"""

from __future__ import annotations
import sys as _sys_io, pathlib as _pathlib_io
_TOOLS_DIR = next(_p for _p in _pathlib_io.Path(__file__).resolve().parents if _p.name == 'tools')
if str(_TOOLS_DIR) not in _sys_io.path:
    _sys_io.path.insert(0, str(_TOOLS_DIR))
from _lib.stdio import ensure_utf8_stdout  # noqa: E402
ensure_utf8_stdout()


import argparse
import hashlib
import json
import lzma
import sys
from pathlib import Path

# Make the sibling library importable when run as a script or as a module.
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from algorithms import (  # noqa: E402
    VAMappingError,
    chacha20_xor,
    go_byte_transform,
    lzma_raw_decompress,
    lzss_decompress,
    rsa_envelope_decrypt,
    rolling_xor,
    rolling_xor_inverse,
    self_check,
    va_to_off,
    xor_add_inverse,
    xor_add_stream,
)

# UTF-8 stdout contract (#317): non-ASCII output (e.g. U+FFFD from
# decode(errors="replace")) must not crash a GBK console — stdout unified on
# UTF-8 with errors="replace" as belt-and-braces for lone surrogates.


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _error(code, message):
    """Print a structured error JSON to stderr and exit with ``code``."""
    print(json.dumps({"error": message, "exit_code": code}), file=sys.stderr)
    sys.exit(code)


def _read_input(args, required=True):
    if args.in_path and args.in_hex:
        _error(2, "give --in or --in-hex, not both")
    if args.in_path:
        try:
            with open(args.in_path, "rb") as f:
                return f.read()
        except OSError as exc:
            _error(2, "cannot read --in %s: %s" % (args.in_path, exc))
    if args.in_hex:
        try:
            return bytes.fromhex(args.in_hex)
        except ValueError as exc:
            _error(2, "invalid --in-hex: %s" % exc)
    if required:
        _error(2, "missing input: need --in or --in-hex")
    return b""


def _write_output(out, args):
    out_path = getattr(args, "out", None)
    if out_path:
        try:
            with open(out_path, "wb") as f:
                f.write(out)
        except OSError as exc:
            _error(2, "cannot write --out %s: %s" % (out_path, exc))


def _emit(rows, args, out=None):
    """Emit a report: field=value lines (default/--reproduce) or JSON."""
    if getattr(args, "out", None) and out is not None:
        _write_output(out, args)
    if args.reproduce:
        for k, v in rows.items():
            print("%s=%s" % (k, v))
    elif args.json:
        print(json.dumps(rows))
    else:
        for k, v in rows.items():
            print("%s=%s" % (k, v))


def _bytes_report(name, data, out, args, extra=None):
    rows = {
        "algorithm": name,
        "input_sha256": _sha256(data),
        "output_sha256": _sha256(out),
        "output_len": len(out),
    }
    if extra:
        rows.update(extra)
    if len(out) <= 64:
        rows["output_hex"] = out.hex()
    _emit(rows, args, out=out)
    return 0


def _negative_report(name, args, **rows):
    """Negative finding: operation ran but produced no result (exit 1)."""
    data = {"algorithm": name, "status": "NEGATIVE"}
    data.update(rows)
    if args.reproduce or not args.json:
        for k, v in data.items():
            print("%s=%s" % (k, v))
    else:
        print(json.dumps(data))
    return 1


def _cmd_chacha(args):
    try:
        key = bytes.fromhex(args.key)
        nonce = bytes.fromhex(args.nonce)
    except ValueError as exc:
        _error(2, "invalid key/nonce hex: %s" % exc)
    data = _read_input(args)
    try:
        out = chacha20_xor(data, key, nonce, counter=args.counter, variant=args.variant)
    except ValueError as exc:
        _error(2, str(exc))
    return _bytes_report("chacha", data, out, args,
                         extra={"variant": args.variant, "counter": args.counter})


def _cmd_xor_add(args):
    data = _read_input(args)
    if args.mode == "decrypt":
        out = xor_add_stream(data, args.key)
    else:
        out = xor_add_inverse(data, args.key)
    return _bytes_report("xor-add", data, out, args,
                         extra={"mode": args.mode, "key": hex(args.key)})


def _cmd_rolling_xor(args):
    data = _read_input(args)
    if args.mode == "decrypt":
        out = rolling_xor(data, args.seed)
    else:
        out = rolling_xor_inverse(data, args.seed)
    return _bytes_report("rolling-xor", data, out, args,
                         extra={"mode": args.mode, "seed": hex(args.seed & 0xFFFFFFFF)})


def _cmd_lzss(args):
    data = _read_input(args)
    try:
        out = lzss_decompress(data, args.size, args.variant)
    except ValueError as exc:
        _error(2, str(exc))
    return _bytes_report("lzss", data, out, args,
                         extra={"variant": args.variant, "size": args.size})


def _cmd_lzma_raw(args):
    data = _read_input(args)
    try:
        out = lzma_raw_decompress(data, dict_size=args.dict_size, lc=args.lc,
                                  lp=args.lp, pb=args.pb, size=args.size)
    except lzma.LZMAError as exc:
        # The input is not a valid LZMA stream -> negative finding.
        return _negative_report("lzma-raw", args, error="LZMAError: %s" % exc,
                                dict_size=hex(args.dict_size), lc=args.lc,
                                lp=args.lp, pb=args.pb)
    return _bytes_report("lzma-raw", data, out, args,
                         extra={"dict_size": hex(args.dict_size), "lc": args.lc,
                                "lp": args.lp, "pb": args.pb})


def _cmd_rsa_unpad(args):
    data = _read_input(args)
    try:
        n = int(args.n, 16)
    except ValueError as exc:
        _error(2, "invalid --n: %s" % exc)
    key_size = args.key_size if args.key_size is not None else n.bit_length()
    try:
        result = rsa_envelope_decrypt(data, n, args.e, key_size, args.mode)
    except ValueError as exc:
        _error(2, str(exc))
    if result["status"] == "FAIL":
        return _negative_report("rsa-unpad", args, mode=args.mode,
                                fail_at_block=result["fail_at_block"],
                                error=result["error"])
    out = result["plaintext"]
    return _bytes_report("rsa-unpad", data, out, args,
                         extra={"mode": args.mode, "n_blocks": result["n_blocks"]})


def _cmd_go_byte_transform(args):
    data = _read_input(args)
    out = go_byte_transform(data, args.key, args.mode)
    return _bytes_report("go-byte-transform", data, out, args,
                         extra={"mode": args.mode, "key": hex(args.key)})


def _cmd_va_to_off(args):
    data = _read_input(args)
    try:
        va = int(args.va, 0)
    except ValueError as exc:
        _error(2, "invalid --va: %s" % exc)
    try:
        off = va_to_off(data, va)
    except VAMappingError as exc:
        return _negative_report("va-to-off", args, va=hex(va), error=str(exc))
    except ValueError as exc:
        _error(2, str(exc))
    rows = {"algorithm": "va-to-off", "input_sha256": _sha256(data),
            "va": hex(va), "file_offset": hex(off)}
    _emit(rows, args)
    return 0


def _cmd_self_check(args):
    try:
        results = self_check()
    except AssertionError as exc:
        _error(2, "self-check FAILED: %s" % exc)
    rows = {"algorithm": "self-check", "status": "PASS"}
    rows.update(results)
    _emit(rows, args)
    return 0


def _build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--in", dest="in_path", metavar="PATH",
                        help="input file path")
    common.add_argument("--in-hex", dest="in_hex", metavar="HEX",
                        help="input bytes as a hex string")
    common.add_argument("--out", metavar="PATH",
                        help="write output bytes to this file")
    common.add_argument("--json", action="store_true",
                        help="print a JSON report to stdout")
    common.add_argument("--reproduce", action="store_true",
                        help="print field=value lines (kunglao L1)")

    ap = argparse.ArgumentParser(
        prog="crypto-tool.py",
        description="Crypto algorithm-library CLI (issue #285): 8 algorithms, pure, idempotent.")
    ap.add_argument("--self-check", action="store_true",
                    help="run every algorithm's roundtrip/known-vector self-check")
    ap.add_argument("--json", action="store_true",
                    help="print a JSON report to stdout (with --self-check)")
    ap.add_argument("--reproduce", action="store_true",
                    help="print field=value lines (with --self-check)")
    sub = ap.add_subparsers(dest="command", metavar="<subcommand>")

    p = sub.add_parser("chacha", parents=[common], help="ChaCha20 XOR stream")
    p.add_argument("--key", required=True, metavar="HEX", help="32-byte key as hex")
    p.add_argument("--nonce", required=True, metavar="HEX", help="12-byte nonce as hex")
    p.add_argument("--counter", type=int, default=0, help="initial block counter (default 0)")
    p.add_argument("--variant", choices=["rfc", "non-rfc"], default="rfc",
                   help="ChaCha schedule: rfc (rot 16/20/24/25) or non-rfc (rot 16/12/8/7)")
    p.set_defaults(func=_cmd_chacha)

    p = sub.add_parser("xor-add", parents=[common], help="XOR/ADD self-syncing stream")
    p.add_argument("--key", type=lambda s: int(s, 0), default=1, help="initial key byte (default 1)")
    p.add_argument("--mode", choices=["decrypt", "encrypt"], default="decrypt",
                   help="decrypt (sample direction) or encrypt (inverse)")
    p.set_defaults(func=_cmd_xor_add)

    p = sub.add_parser("rolling-xor", parents=[common], help="32-bit-state rolling XOR")
    p.add_argument("--seed", type=lambda s: int(s, 0), default=0x963239FD,
                   help="32-bit seed (default 0x963239fd)")
    p.add_argument("--mode", choices=["decrypt", "encrypt"], default="decrypt",
                   help="decrypt (sample direction) or encrypt (inverse)")
    p.set_defaults(func=_cmd_rolling_xor)

    p = sub.add_parser("lzss", parents=[common], help="LZ decompressor (py/dll variants)")
    p.add_argument("--variant", choices=["py", "dll"], default="py",
                   help="py: exact output size; dll: dst-capacity bound")
    p.add_argument("--size", type=int, required=True, help="expected output size / capacity")
    p.set_defaults(func=_cmd_lzss)

    p = sub.add_parser("lzma-raw", parents=[common], help="raw LZMA1 decompression")
    p.add_argument("--dict-size", type=lambda s: int(s, 0), default=0x800000)
    p.add_argument("--lc", type=int, default=3)
    p.add_argument("--lp", type=int, default=0)
    p.add_argument("--pb", type=int, default=2)
    p.add_argument("--size", type=int, default=None,
                   help="cap output size (streams without end marker)")
    p.set_defaults(func=_cmd_lzma_raw)

    p = sub.add_parser("rsa-unpad", parents=[common], help="RSA-envelope unpadding")
    p.add_argument("--mode", required=True, choices=["PKCS1v15", "OAEP-SHA1", "OAEP-SHA256"])
    p.add_argument("--n", required=True, metavar="HEX", help="RSA modulus n (hex)")
    p.add_argument("--e", type=lambda s: int(s, 0), default=65537, help="RSA exponent (default 65537)")
    p.add_argument("--key-size", type=int, default=None,
                   help="key bit length (default: derived from n)")
    p.set_defaults(func=_cmd_rsa_unpad)

    p = sub.add_parser("go-byte-transform", parents=[common], help="Go byte transform")
    p.add_argument("--key", type=lambda s: int(s, 0), default=0x17182, help="transform key (default 0x17182)")
    p.add_argument("--mode", choices=["forward", "inverse"], default="inverse",
                   help="forward = sample runtime decrypt; inverse = encrypt")
    p.set_defaults(func=_cmd_go_byte_transform)

    p = sub.add_parser("va-to-off", parents=[common], help="PE VA -> file offset")
    p.add_argument("--va", required=True, metavar="HEX", help="virtual address to map (hex)")
    p.set_defaults(func=_cmd_va_to_off)

    return ap


def main(argv=None):
    ap = _build_parser()
    args = ap.parse_args(argv)
    if args.self_check:
        return _cmd_self_check(args)
    if not getattr(args, "func", None):
        ap.print_help(sys.stderr)
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
