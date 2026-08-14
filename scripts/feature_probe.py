# -*- coding: utf-8 -*-
"""feature_probe.py — fast deterministic sample-feature probe (issue #278 P4-a).

Stdlib-only, pure bytes parsing (no pefile): reads the PE header directly.

Features extracted from <sample_path>:
  machine         COFF Machine field mapped to a name (AMD64/I386/ARM64/...,
                  hex fallback for unknown values)
  sections        [{name, vaddr, raw_size}] parsed from the section table
  overlay         trailing bytes beyond the last section's raw end
  entropy         Shannon entropy over a 256-bin histogram of the first
                  SAMPLE_CAP bytes, normalized to 0..8 against the
                  sample-size ceiling and capped at 8
  string_density  printable-ASCII run bytes (runs >= 4 chars) / sampled bytes
  import_hints    unique printable-ASCII runs >= 4 chars (order preserved,
                  capped at MAX_HINTS) — import-table name strings via scan

Exit codes:
  0  ok
  2  usage error
  3  file missing, unreadable, or not a PE (clear message, no crash)

Workspace-agnostic: the sample path is an argument; no hardcoded paths.

Usage:
  python scripts/feature_probe.py sample.exe
  python scripts/feature_probe.py sample.exe --json
"""
from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from pathlib import Path

SAMPLE_CAP = 64 * 1024    # scan window: entropy/density/hints use first 64KB
MIN_RUN = 4               # min printable-ASCII run length counted
MAX_SECTIONS = 96         # Windows section-count ceiling
MAX_HINTS = 64            # cap on reported import hints
PRINTABLE_MIN = 0x20
PRINTABLE_MAX = 0x7E
HIST_BINS = 256

PE_SIG = b"PE\x00\x00"
COFF_SIZE = 20
SECTION_HDR_SIZE = 40

MACHINE_NAMES = {
    0x14C: "I386",
    0x8664: "AMD64",
    0xAA64: "ARM64",
    0x1C0: "ARM",
    0x1C4: "ARMNT",
    0x200: "IA64",
}


class NotPE(Exception):
    """Raised when the bytes cannot be parsed as a PE (clear message)."""


def _need(data: bytes, off: int, size: int, what: str) -> None:
    """Bounds-check a struct read: any read past the buffer must land on
    NotPE (exit 3), never on a struct.error traceback."""
    if off < 0 or off + size > len(data):
        raise NotPE(f"truncated PE header (missing {what})")


def read_sample(path: Path) -> bytes:
    """Read the first SAMPLE_CAP bytes of the sample (bounded memory)."""
    with open(path, "rb") as fh:
        return fh.read(SAMPLE_CAP)


def parse_pe(data: bytes, file_size: int) -> dict:
    """Parse MZ/PE headers + section table. Raises NotPE on any violation."""
    if len(data) < 0x40:
        raise NotPE("file too small to hold a DOS header")
    if data[0:2] != b"MZ":
        raise NotPE("missing MZ magic")
    (e_lfanew,) = struct.unpack_from("<I", data, 0x3C)
    if e_lfanew + len(PE_SIG) > len(data):
        raise NotPE(f"PE header offset 0x{e_lfanew:x} beyond scan window")
    if data[e_lfanew:e_lfanew + 4] != PE_SIG:
        raise NotPE("missing PE signature")
    _need(data, e_lfanew + 4, 4, "COFF machine/section-count")
    machine, nsections = struct.unpack_from("<HH", data, e_lfanew + 4)
    _need(data, e_lfanew + 20, 2, "SizeOfOptionalHeader")
    (sizeof_opt,) = struct.unpack_from("<H", data, e_lfanew + 20)
    if nsections == 0 or nsections > MAX_SECTIONS:
        raise NotPE(f"implausible section count {nsections}")

    sections: list[dict] = []
    raw_end = 0
    sec_start = e_lfanew + 4 + COFF_SIZE + sizeof_opt
    for i in range(nsections):
        off = sec_start + i * SECTION_HDR_SIZE
        if off + SECTION_HDR_SIZE > len(data):
            raise NotPE("section table truncated")
        name_raw = data[off:off + 8]
        name = name_raw.split(b"\x00", 1)[0].decode("ascii", "replace")
        vaddr = struct.unpack_from("<I", data, off + 12)[0]
        raw_size = struct.unpack_from("<I", data, off + 16)[0]
        raw_ptr = struct.unpack_from("<I", data, off + 20)[0]
        sections.append({"name": name, "vaddr": vaddr, "raw_size": raw_size})
        raw_end = max(raw_end, raw_ptr + raw_size)

    return {
        "machine": MACHINE_NAMES.get(machine, f"0x{machine:04x}"),
        "sections": sections,
        "overlay": raw_end < file_size,
    }


def shannon_entropy(data: bytes) -> float:
    """256-bin Shannon entropy, normalized to 0..8 and capped at 8.

    Raw Shannon entropy tops out at log2(256) = 8 only when every bin can be
    occupied; for samples smaller than 256 bytes the achievable ceiling is
    log2(len(data)), so the value is normalized against that ceiling.
    """
    n = len(data)
    if n == 0:
        return 0.0
    counts = [0] * HIST_BINS
    for b in data:
        counts[b] += 1
    raw = 0.0
    for c in counts:
        if c:
            p = c / n
            raw -= p * math.log2(p)
    ceiling = math.log2(min(n, HIST_BINS))
    if ceiling <= 0.0:
        return 0.0
    return min(8.0, raw / ceiling * 8.0)


def ascii_runs(data: bytes) -> list[tuple[str, int]]:
    """Maximal printable-ASCII runs of length >= MIN_RUN, in order."""
    runs: list[tuple[str, int]] = []
    start = None
    for i, b in enumerate(data + b"\x00"):  # sentinel ends a trailing run
        printable = PRINTABLE_MIN <= b <= PRINTABLE_MAX
        if printable and start is None:
            start = i
        elif not printable and start is not None:
            if i - start >= MIN_RUN:
                runs.append((data[start:i].decode("ascii", "replace"),
                             i - start))
            start = None
    return runs


def string_features(data: bytes) -> tuple[float, list[str]]:
    """string_density (run bytes / sampled bytes) + deduped import hints."""
    runs = ascii_runs(data)
    run_bytes = sum(length for _, length in runs)
    density = run_bytes / len(data) if data else 0.0
    hints: list[str] = []
    seen: set[str] = set()
    for text, _ in runs:
        if text not in seen:
            seen.add(text)
            hints.append(text)
        if len(hints) >= MAX_HINTS:
            break
    return density, hints


def format_text(result: dict) -> str:
    sections = " ".join(f"{s['name']}(vaddr=0x{s['vaddr']:x},"
                        f"raw_size=0x{s['raw_size']:x})"
                        for s in result["sections"])
    lines = [
        f"machine: {result['machine']}",
        f"sections: {sections}",
        f"overlay: {'true' if result['overlay'] else 'false'}",
        f"entropy: {result['entropy']:.4f}",
        f"string_density: {result['string_density']:.4f}",
        f"import_hints: {' '.join(result['import_hints'])}",
    ]
    return "\n".join(lines)


def probe(path: Path) -> dict:
    """Full probe: header parse + entropy/density/hints over the scan window."""
    data = read_sample(path)
    header = parse_pe(data, path.stat().st_size)
    density, hints = string_features(data)
    return {
        **header,
        "entropy": round(shannon_entropy(data), 4),
        "string_density": round(density, 4),
        "import_hints": hints,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="fast deterministic sample-feature probe (issue #278 P4-a)")
    ap.add_argument("sample_path", help="path to the PE sample")
    ap.add_argument("--json", action="store_true",
                    help="emit JSON instead of text lines")
    args = ap.parse_args(argv)

    path = Path(args.sample_path)
    if not path.is_file():
        print(f"error: sample file not found: {path}", file=sys.stderr)
        return 3
    try:
        result = probe(path)
    except NotPE as exc:
        print(f"error: {path} is not a PE file: {exc}", file=sys.stderr)
        return 3
    except OSError as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(format_text(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
