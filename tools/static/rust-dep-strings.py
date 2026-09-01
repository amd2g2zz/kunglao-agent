#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/static/rust-dep-strings.py — Rust crate dependency-string carving (issue #427).

Absorbed from:
- ghidra_scripts/RustDependencyStrings.py (Ghidra community
  script, author Matt Ehrnschwender, @category Search) — its cargo registry
  path regex
  ``.cargo(/|\\)registry(/|\\)src(/|\\).*?-[a-f0-9]{16}(/|\\)(crate-ver)``
  is the absorbed data asset, adapted below to a marker + bounded-window +
  backtrack-extraction form; the original's whole-section readAllBytes +
  printable-filter + concat read is deliberately NOT carried over (it can
  join non-adjacent sections into matches that exist in neither).
- Everything else (dual-channel scan, #277 CLI contract, JSON schema) is
  self-built.

Channels (selectable via --channels):
  registry  cargo registry paths ``registry[/\\](src|cache|index)[/\\]<host>-<16hex>[/\\]<crate>-<version>``
            (registry ids: e.g. index.crates.io-6f17d22bba15001f,
            github.com-1ecc6299db9ec823), bare registry ids, and
            ``registry+<scheme>://`` SourceId URLs;
  crate     standalone ``<crate-name>-<semver>`` byte strings.

Usage:
  rust-dep-strings --in sample.bin
  rust-dep-strings --in sample.bin --channels registry
  rust-dep-strings --in sample.bin --json / --reproduce

Exit codes: 0 = found >=1 dependency-string hit (crate / registry id /
registry source), 1 = negative finding (input scanned, nothing found),
2 = error (bad args / unreadable input).  Errors print a structured JSON
object to stderr: {"error": "...", "exit_code": 2}.
"""
from __future__ import annotations
import sys as _sys_io, pathlib as _pathlib_io
_TOOLS_DIR = next(_p for _p in _pathlib_io.Path(__file__).resolve().parents if _p.name == 'tools')
if str(_TOOLS_DIR) not in _sys_io.path:
    _sys_io.path.insert(0, str(_TOOLS_DIR))
from _lib.stdio import ensure_utf8_stdout  # noqa: E402
ensure_utf8_stdout()


import argparse
import re
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from common import (  # noqa: E402
    add_common_flags,
    error,
    negative,
    read_bytes,
    report,
    sha256,
)

# UTF-8 stdout contract (#317): non-ASCII output (e.g. U+FFFD from
# decode(errors="replace")) must not crash a GBK console — stdout unified on
# UTF-8 with errors="replace" as belt-and-braces for lone surrogates.

VALID_CHANNELS = ("registry", "crate")
MARKER = b"registry"
# After a `registry` marker: the cargo subdirectory kind (src/cache/index).
KIND_AFTER_RE = re.compile(rb"[/\\](src|cache|index)[/\\]")
# Registry id = <host-with-dots>-<16 hex> (e.g. github.com-1ecc6299db9ec823,
# index.crates.io-6f17d22bba15001f). The dotted-host prefix is required so a
# plain binary's stray 16-hex runs do not register as cargo evidence.
REG_ID_RE = re.compile(rb"(?<![A-Za-z0-9.-])"
                       rb"(?:[A-Za-z0-9-]+\.)+[A-Za-z0-9-]{2,}-[a-f0-9]{16}"
                       rb"(?![a-f0-9])")
# Cargo SourceId replacement URLs (registry+https://...).
SOURCE_URL_RE = re.compile(rb"registry\+[A-Za-z][A-Za-z0-9+.-]{1,10}://"
                           rb"[^\x00\s\"'<>]{3,200}")
# <crate-name>-<semver> with optional prerelease/build tail; the trailing
# guard rejects digit/letter continuations (partial-version false hits).
CRATE_VER_RE = re.compile(rb"([A-Za-z][A-Za-z0-9_-]{0,63})"
                          rb"-(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)(?![0-9A-Za-z])")
# Standalone crate strings: lowercase crate charset, bounded away from
# surrounding token characters so inner-name fragments do not match.
STANDALONE_RE = re.compile(rb"(?<![A-Za-z0-9_.-])"
                           rb"([a-z][a-z0-9_-]{0,63})-"
                           rb"(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)(?![0-9A-Za-z])")
SEP_RE = re.compile(rb"[/\\]")
KIND_WINDOW = 16        # bytes allowed between `registry` and (src|cache|index)
ID_MAX = 80             # max registry-id token length
TAIL_WINDOW = 120       # backtrack-extraction window after the registry id
MAX_OFFSETS = 32        # per-row offset cap (unbounded lists are a hazard)
# Cargo cache archives are named exactly `<crate>-<version>.crate`; on a
# prerelease version the greedy tail charset `[0-9A-Za-z.-]+` swallows this
# suffix into the extracted version (src paths end in `/` and are immune) —
# strip exactly one literal suffix on the cache kind (M1).
CRATE_ARCHIVE_SUFFIX = ".crate"


def _add_crate(crates: dict, name: str, version: str, channel: str,
               offset: int, reg_id: str | None, kind: str | None) -> None:
    row = crates.get((name, version))
    if row is None:
        row = {"crate": name, "version": version, "channels": [],
               "offsets": [], "registry": reg_id, "path_kind": kind}
        crates[(name, version)] = row
    if channel not in row["channels"]:
        row["channels"].append(channel)
    row["offsets"].append(offset)


def _scan_registry_paths(data: bytes) -> list[dict]:
    """Marker walk + bounded windows + backtrack extraction.

    Every component (kind, registry id, crate-version tail) is read from a
    window bounded around its marker, so a hit can never span two
    non-adjacent byte regions — the anti-cross-section replacement for the
    absorbed script's printable-concat read.  Returns the raw hits; channel
    selection happens in :func:`carve`.
    """
    hits = []
    pos = 0
    while True:
        idx = data.find(MARKER, pos)
        if idx < 0:
            return hits
        pos = idx + 1
        km = KIND_AFTER_RE.search(data, idx + len(MARKER),
                                  idx + len(MARKER) + KIND_WINDOW)
        if km is None:
            continue
        idm = REG_ID_RE.match(data, km.end())
        if idm is None or idm.end() - km.end() > ID_MAX:
            continue
        reg_id = idm.group(0).decode("ascii")
        kind = km.group(1).decode("ascii")
        tail = data[idm.end():idm.end() + TAIL_WINDOW]
        sm = SEP_RE.match(tail)
        if sm is None:
            continue
        cv = CRATE_VER_RE.match(tail, sm.end())
        if cv is None:
            continue  # backtrack rejection: no <name>-<semver> tail
        version = cv.group(2).decode("ascii")
        if kind == "cache" and version.endswith(CRATE_ARCHIVE_SUFFIX):
            version = version[: -len(CRATE_ARCHIVE_SUFFIX)]
        hits.append({"offset": idx, "span_end": idm.end() + cv.end(),
                     "crate": cv.group(1).decode("ascii"),
                     "version": version,
                     "registry": reg_id, "path_kind": kind})


def carve(data: bytes, channels: list[str]) -> dict:
    """Extract Rust dependency strings on the selected channels."""
    crates: dict = {}
    registry_ids: dict[str, list[int]] = {}
    sources: list[dict] = []

    path_hits = _scan_registry_paths(data)
    spans = [(h["offset"], h["span_end"]) for h in path_hits]
    if "registry" in channels:
        for h in path_hits:
            _add_crate(crates, h["crate"], h["version"], "registry",
                       h["offset"], h["registry"], h["path_kind"])
        for m in REG_ID_RE.finditer(data):
            registry_ids.setdefault(m.group(0).decode("ascii"),
                                    []).append(m.start())
        for m in SOURCE_URL_RE.finditer(data):
            sources.append({"url": m.group(0).decode("utf-8", "replace"),
                            "offset": m.start()})

    if "crate" in channels:
        for m in STANDALONE_RE.finditer(data):
            if any(a <= m.start() < b for a, b in spans):
                continue  # already counted via its registry path
            _add_crate(crates, m.group(1).decode("ascii"),
                       m.group(2).decode("ascii"), "crate", m.start(),
                       None, None)

    return {"crates": crates, "registry_ids": registry_ids, "sources": sources}


def _capped(offsets: list[int]) -> tuple[list[int], bool]:
    return offsets[:MAX_OFFSETS], len(offsets) > MAX_OFFSETS


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="rust-dep-strings",
        description="Rust crate dependency-string carving (issue #427)")
    add_common_flags(ap)
    ap.add_argument("--channels", default="registry,crate", metavar="LIST",
                    help="comma-separated channels to scan "
                         "(registry,crate; default: both)")
    args = ap.parse_args(argv)

    # N1: dedup repeated values in first-seen order — `registry,registry`
    # scans one channel and is echoed once on every output face.
    channels = list(dict.fromkeys(
        c.strip() for c in args.channels.split(",") if c.strip()))
    bad = [c for c in channels if c not in VALID_CHANNELS]
    if not channels or bad:
        error(f"invalid --channels {args.channels!r}: expected a comma-"
              f"separated subset of {'/'.join(VALID_CHANNELS)} — "
              f"e.g. --channels registry")

    data = read_bytes(args.in_path)
    input_sha = sha256(data)
    found = carve(data, channels)

    crates = sorted(found["crates"].values(), key=lambda r: r["offsets"][0])
    reg_rows = []
    for reg_id in sorted(found["registry_ids"],
                         key=lambda i: found["registry_ids"][i][0]):
        offs, capped = _capped(found["registry_ids"][reg_id])
        reg_rows.append({"id": reg_id, "offsets": offs,
                         "offsets_capped": capped})
    sources = sorted(found["sources"], key=lambda s: s["offset"])
    total = len(crates)

    if not (crates or reg_rows or sources):
        return negative(args, "rust-dep-strings",
                        channels=",".join(channels), total=0,
                        registry_ids=0, registry_sources=0)

    if crates:
        text_lines = [
            f"off=0x{row['offsets'][0]:x} crate={row['crate']} "
            f"version={row['version']} channels={','.join(row['channels'])} "
            f"registry={row['registry'] or '-'} kind={row['path_kind'] or '-'}"
            for row in crates
        ]
    else:
        # registry evidence without crates (ids / source URLs only)
        text_lines = [
            f"off=0x{row['offsets'][0]:x} registry_id={row['id']}"
            for row in reg_rows
        ] + [
            f"off=0x{s['offset']:x} registry_source={s['url']}"
            for s in sources
        ]
    json_obj = {
        "tool": "rust-dep-strings",
        "input_sha256": input_sha,
        "channels": channels,
        "total": total,
        "crates": [
            {**{k: row[k] for k in ("crate", "version", "channels",
                                    "registry", "path_kind")},
             "offsets": _capped(row["offsets"])[0],
             "offsets_capped": _capped(row["offsets"])[1]}
            for row in crates
        ],
        "registry_ids": reg_rows,
        "registry_sources": sources,
    }
    reproduce_rows = {
        "tool": "rust-dep-strings",
        "input_sha256": input_sha,
        "channels": ",".join(channels),
        "total": total,
    }
    if crates:
        first = crates[0]
        reproduce_rows.update({
            "first_crate": first["crate"],
            "first_version": first["version"],
            "first_channel": first["channels"][0],
        })
    elif reg_rows:
        reproduce_rows["first_registry_id"] = reg_rows[0]["id"]
    return report(args, text_lines, json_obj, reproduce_rows)


if __name__ == "__main__":
    sys.exit(main())
