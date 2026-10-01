#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ws_yaml.py — YAML-safe get/set/del for worker-writable workspace state
(#482: hand-edited YAML with unquoted colons corrupted the claim register
and crashed the convergence face for three consecutive runs).

Workers edit registers/ledgers through THIS tool instead of hand-editing:
every write goes safe_load -> mutate -> safe_dump -> re-load validate
(a write that does not round-trip is refused, exit 4). Dotted paths
address nesting; numeric segments index lists (claims.3.evidence).

Usage:
  python3 ws_yaml.py get  <file> <dotted.path>
  python3 ws_yaml.py set  <file> <dotted.path> <value>
  python3 ws_yaml.py del  <file> <dotted.path>
Exit codes: 0 ok / 2 usage / 3 unreadable-or-invalid target / 4 refused
(non-round-tripping write) / 5 path-not-found (get/del).
"""
from __future__ import annotations

import sys

import yaml


def _walk(doc, segments, *, create=False):
    node = doc
    for i, seg in enumerate(segments):
        last = i == len(segments) - 1
        if isinstance(node, list):
            try:
                idx = int(seg)
            except ValueError:
                raise KeyError(seg)
            if idx >= len(node):
                raise KeyError(seg)
            if last:
                return node, idx
            node = node[idx]
        elif isinstance(node, dict):
            if last:
                return node, seg
            if create and seg not in node:
                node[seg] = {}
            if seg not in node:
                raise KeyError(seg)
            node = node[seg]
        else:
            raise KeyError(seg)
    raise KeyError(".".join(segments))


def _coerce(raw: str):
    """Scalar literals stay literal-string ONLY when quoted; otherwise
    yaml-load the single scalar so numbers/bools keep their types."""
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
        return raw[1:-1]
    try:
        return yaml.safe_load(raw)
    except yaml.YAMLError:
        return raw


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 3 or argv[0] not in ("get", "set", "del"):
        print(__doc__.split("Usage:")[0], file=sys.stderr)
        return 2
    cmd, path, dotted = argv[0], argv[1], argv[2]
    segments = [s for s in dotted.split(".") if s != ""]
    if not segments:
        return 2
    try:
        with open(path, encoding="utf-8") as fh:
            doc = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as exc:
        print(f"ws_yaml: unreadable/invalid target: {exc}", file=sys.stderr)
        return 3
    if doc is None:
        doc = {}
    try:
        if cmd == "get":
            node, key = _walk(doc, segments)
            print(yaml.safe_dump([node[key]], default_flow_style=True)
                  .strip()[1:-1].strip())
            return 0
        if cmd == "del":
            node, key = _walk(doc, segments)
            del node[key]
        else:  # set
            if len(argv) < 4:
                return 2
            node, key = _walk(doc, segments, create=True)
            node[key] = _coerce(argv[3])
    except KeyError as exc:
        print(f"ws_yaml: path not found: {dotted} ({exc})", file=sys.stderr)
        return 5
    text = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True,
                          default_flow_style=False)
    if yaml.safe_load(text) != doc:  # refuse non-round-tripping writes
        print("ws_yaml: write refused (non-round-tripping)",
              file=sys.stderr)
        return 4
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
