#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ws_yaml.py — YAML-safe get/set/del/append for worker-writable workspace
state (#482: hand-edited YAML with unquoted colons corrupted the claim
register and crashed the convergence face for three consecutive runs).

Workers edit registers/ledgers through THIS tool instead of hand-editing:
every write goes safe_load -> mutate -> safe_dump -> re-load validate
(a write that does not round-trip is refused, exit 4). Dotted paths
address nesting; numeric segments index lists (claims.3.evidence).
`append` adds one scalar to the list at <dotted.path>. The parent path
must already exist; an ABSENT final key under a mapping materializes as
an empty list (the first item), while an EXISTING non-list target is
refused (exit 3) — a scalar is never silently coerced into a list. No
nested structure is invented: the value is one scalar, list-valued
fields grow one sanctioned item at a time instead of by replacing the
whole list through a container literal.

Usage:
  python3 ws_yaml.py get  <file> <dotted.path>
  python3 ws_yaml.py set  <file> <dotted.path> <value>
  python3 ws_yaml.py del  <file> <dotted.path>
  python3 ws_yaml.py append <file> <dotted.path> <value>
Exit codes: 0 ok / 2 usage / 3 unreadable-or-invalid target / 4 refused
(non-round-tripping write) / 5 path-not-found (get/del/append).
"""
from __future__ import annotations

import re
import sys

from pathlib import Path

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
    yaml-load the single scalar so numbers/bools keep their types.

    #516: a bare load that yields a CONTAINER (dict/list — prose carrying
    `key: value` inside it parses as a mapping) falls back to the literal
    string. The unquoted-prose-with-colon shape is exactly the four-run
    register corruption class; the setter must never turn it into a
    mapping. Nested values are set through dotted paths, one scalar at a
    time, so container coercion has no legitimate caller."""
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
        return raw[1:-1]
    try:
        loaded = yaml.safe_load(raw)
    except yaml.YAMLError:
        return raw
    if isinstance(loaded, (dict, list)):
        return raw
    return loaded


# #516: THE canonical register serialization, single-sourced here because
# ws_yaml.py is the register's only sanctioned tool-face mutator — the
# write guard's round-trip adjudication and every ws_yaml write agree by
# construction instead of by kwargs copy-drift.
CANONICAL_KWARGS = dict(sort_keys=False, allow_unicode=True,
                        default_flow_style=False)


def canonical_dump(doc) -> str:
    """The single-writer rendering (#516). Hand-typed YAML — valid or not —
    is refused at the write gate; only this serialization passes."""
    return yaml.safe_dump(doc, **CANONICAL_KWARGS)


# #630: the template-version stamp is a COMMENT line (#536 carriers:
# CLAUDE.md / facts/_INDEX.md / claim-register.yaml); safe_dump drops
# every comment, so the register's single-writer rewrites silently
# stripped its stamp — hooks_selfcheck reported
# "template_version stamp faults: claim-register.yaml=missing" on every
# tick. Re-emit the stamp on write: preserve a found value (an older
# value must SURVIVE as the visible upgrade signal); an absent register
# stamp recovers from the same-dir CLAUDE.md carrier (correct for both
# the skill and the deployed copy), then the active skill version.
_STAMP_RE = re.compile(r"^#\s*kunglao_template_version:\s*(\S+)",
                       re.MULTILINE)


def _stamp_value(old_text: str, path) -> str | None:
    m = _STAMP_RE.search(old_text)
    if m:
        return m.group(1)
    if Path(path).name != "claim-register.yaml":
        return None
    try:
        sibling = (Path(path).resolve().parent / "CLAUDE.md").read_text(
            encoding="utf-8", errors="replace")
        m2 = _STAMP_RE.search(sibling)
        if m2:
            return m2.group(1)
    except OSError as exc:
        from kunglao_log import warn
        warn("ws_yaml_stamp_read", f"{type(exc).__name__}: {exc}")
    try:
        import template_version as _tv
        return _tv.read_skill_version()
    except Exception:  # noqa: BLE001 — off-tree copy: no version source
        return None


def _stamp_prefix(old_text: str, path) -> str:
    value = _stamp_value(old_text, path)
    return f"# kunglao_template_version: {value}\n" if value else ""


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 3 or argv[0] not in ("get", "set", "del", "append"):
        print(__doc__.split("Usage:")[0], file=sys.stderr)
        return 2
    cmd, path, dotted = argv[0], argv[1], argv[2]
    segments = [s for s in dotted.split(".") if s != ""]
    if not segments:
        return 2
    try:
        with open(path, encoding="utf-8") as fh:
            old_text = fh.read()
            doc = yaml.safe_load(old_text)
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
        elif cmd == "append":
            if len(argv) < 4:
                return 2
            node, key = _walk(doc, segments)  # parent path must exist
            if isinstance(node, dict) and key not in node:
                node[key] = []  # first item materializes the list
            cur = node[key]
            if not isinstance(cur, list):
                print(f"ws_yaml: append target is not a list: {dotted} "
                      f"({type(cur).__name__})", file=sys.stderr)
                return 3
            node[key] = [*cur, _coerce(argv[3])]
        else:  # set
            if len(argv) < 4:
                return 2
            node, key = _walk(doc, segments, create=True)
            node[key] = _coerce(argv[3])
    except KeyError as exc:
        print(f"ws_yaml: path not found: {dotted} ({exc})", file=sys.stderr)
        return 5
    text = canonical_dump(doc)
    if yaml.safe_load(text) != doc:  # refuse non-round-tripping writes
        print("ws_yaml: write refused (non-round-tripping)",
              file=sys.stderr)
        return 4
    text = _stamp_prefix(old_text, path) + text
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    if cmd != "get" and Path(path).name == "claim-register.yaml":
        # matrix4b G2: the sanctioned register write settles its claim
        # transitions (the settlement ledger face). Workers write the register
        # ONLY through this tool (single-writer), so without this leg
        # every real promotion lands row-less and the C7 settlement
        # gate starves. Fail-open: observability never breaks the set.
        try:
            from register_proven_gate import emit_settlements
            emit_settlements(Path(path).parent, text, old_text)
        except Exception as exc:  # noqa: BLE001 — never breaks the write
            from kunglao_log import warn
            warn("ws_yaml.settle", f"{type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
