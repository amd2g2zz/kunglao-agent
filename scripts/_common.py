#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_common.py — THE shared leaf-utility module (the dedup home the
owner's consolidation ruling names). A leaf by contract: numpy +
PyYAML + stdlib ONLY — never imports any repo module, so every
importer family (settlement, state, kernel, hooks) can depend on it
without crossing its isolation walls. Duplicated helpers migrate here;
the formal_code_lint ledger shrinks as they do."""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import time
from collections.abc import Iterable
from pathlib import Path

import numpy as np
import yaml


def seq_sum(values: Iterable[float]) -> float:
    """Input-order float64 reduction — the settlement determinism axiom
    ("float sums in input order") as a numpy primitive.

    np.add.accumulate is strictly left-to-right IEEE-754 double addition;
    the prepended 0.0 seed makes it bit-identical to a Python in-order
    sum for every finite input, and — unlike builtin sum(), which
    switched floats to Neumaier compensation in 3.12 — identical on
    every interpreter. np.sum / np.add.reduce are FORBIDDEN on this
    path: pairwise summation reorders the bits, and the pins in the
    bit-exact suites are the wall. THE canonical implementation (the
    per-module redeclarations are retired).
    """
    arr = np.asarray(list(values), dtype=np.float64)
    if arr.size == 0:
        return 0.0
    return float(np.add.accumulate(np.concatenate(([0.0], arr)))[-1])


def utc_now_z() -> str:
    """THE canonical UTC timestamp face: ISO-8601 Z, second precision —
    one format everywhere a wall-clock stamp is written."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha256_hex(data: bytes) -> str:
    """THE canonical bytes→digest face: lowercase hex sha256, one line
    everywhere a hash of some bytes is written."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    """THE canonical file→digest face: lowercase hex sha256 over the
    file's contents, read in chunks (constant memory; the digest is
    identical to a whole-file read — chunking cannot move a hash)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_yaml(path: str | Path) -> tuple[dict | None, str | None]:
    """THE canonical tolerant YAML read: ``(doc, error)``.

    ``doc`` is the parsed mapping on success (``None`` otherwise);
    ``error`` is ``None`` on success and a short ``"<Type>: <msg>"``
    string otherwise. Missing files, unreadable bytes, malformed YAML
    and non-mapping documents all degrade to ``(None, reason)`` — the
    leaf never warns, raises or decides: the error string travels back
    so each caller keeps its own degrade policy (warn, skip, default).
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
        doc = yaml.safe_load(text)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if not isinstance(doc, dict):
        return None, "yaml document is not a mapping"
    return doc, None


def atomic_write_text(path: str | Path, text: str, *,
                      unique: bool = False,
                      mode: int | None = None) -> Path:
    """THE canonical atomic text write: same-directory tmp +
    ``os.replace``. Missing parent directories are created; the
    destination is never observed half-written (a same-filesystem
    rename is atomic; a tmp in another directory could degrade to
    copy+delete). Callers serialize their own payload (json.dumps,
    yaml.safe_dump, plain text) — the leaf only guards the write.

    ``unique=True`` takes a writer-unique tmp name (mkstemp) so two
    concurrent writers on one destination never share a buffer (the
    two-writer tear); the plain face is single-writer by contract.
    ``mode`` chmods the final file before the rename (destination-mode
    or fixed parity). A failed write unlinks its tmp — never silent
    residue."""
    return _atomic_write(path, text, False, unique=unique, mode=mode)


def atomic_write_bytes(path: str | Path, data: bytes, *,
                       unique: bool = False,
                       mode: int | None = None) -> Path:
    """The bytes face of the canonical atomic write — same contract as
    ``atomic_write_text`` for binary payloads."""
    return _atomic_write(path, data, True, unique=unique, mode=mode)


def _atomic_write(path: str | Path, payload, binary: bool, *,
                  unique: bool, mode: int | None) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if unique:
        fd, name = tempfile.mkstemp(dir=p.parent, prefix=p.name + ".",
                                    suffix=".tmp")
        tmp = Path(name)
        try:
            if binary:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(payload)
            else:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(payload)
        except BaseException:
            _cleanup_tmp(tmp)
            raise
    else:
        tmp = p.with_name(p.name + ".tmp")
        if binary:
            tmp.write_bytes(payload)
        else:
            tmp.write_text(payload, encoding="utf-8")
    try:
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, p)
    except BaseException:
        _cleanup_tmp(tmp)
        raise
    return p


def _cleanup_tmp(tmp: Path) -> None:
    """Best-effort tmp removal during exception propagation. The leaf
    cannot reach the repo rate-limited logger (isolation), so the
    one-trace rule survives as a stderr line — never a silent pass."""
    try:
        tmp.unlink()
    except OSError as exc:
        print(f"[kunglao-agent] atomic-write tmp cleanup failed for "
              f"{tmp.name}: {type(exc).__name__}: {exc}",
              file=sys.stderr)
