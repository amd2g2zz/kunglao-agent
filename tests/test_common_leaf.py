# -*- coding: utf-8 -*-
"""Pins for the shared leaf-utility module ``scripts/_common.py``.

The leaf is the one dedup home (numpy + PyYAML + stdlib, never a repo
import). These pins lock the public contracts the migration families
depend on: sha256 faces (bytes / file) and the tolerant YAML read that
returns ``(doc, error)`` so every caller keeps its own warn policy.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

sys_path = Path(__file__).resolve().parents[1] / "scripts"
if str(sys_path) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(sys_path))

from _common import (atomic_write_bytes, atomic_write_text,  # noqa: E402
                     read_yaml, scripts_bootstrap, sha256_file, sha256_hex)

ABC_SHA = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


# ---------- sha256_hex ----------

def test_sha256_hex_known_vector():
    assert sha256_hex(b"abc") == ABC_SHA


def test_sha256_hex_empty():
    assert sha256_hex(b"") == hashlib.sha256(b"").hexdigest()


def test_sha256_hex_matches_hashlib_directly():
    blob = b"\x00\x01\xffchunked\x0a"
    assert sha256_hex(blob) == hashlib.sha256(blob).hexdigest()


# ---------- sha256_file ----------

def test_sha256_file_matches_whole_file_read(tmp_path):
    p = tmp_path / "blob.bin"
    p.write_bytes(b"line1\nline2\x00binary\xff")
    assert sha256_file(p) == hashlib.sha256(p.read_bytes()).hexdigest()


def test_sha256_file_empty_file(tmp_path):
    p = tmp_path / "empty.bin"
    p.write_bytes(b"")
    assert sha256_file(p) == hashlib.sha256(b"").hexdigest()


def test_sha256_file_accepts_str_path(tmp_path):
    p = tmp_path / "s.txt"
    p.write_text("hello", encoding="utf-8")
    assert sha256_file(str(p)) == sha256_file(p)


def test_sha256_file_missing_raises(tmp_path):
    with pytest.raises(OSError):
        sha256_file(tmp_path / "nope.bin")


# ---------- read_yaml: the (doc, error) tuple contract ----------

def test_read_yaml_valid_mapping(tmp_path):
    p = tmp_path / "ok.yaml"
    p.write_text("a: 1\nb: [x, y]\n", encoding="utf-8")
    doc, err = read_yaml(p)
    assert err is None
    assert doc == {"a": 1, "b": ["x", "y"]}


def test_read_yaml_returns_exactly_a_pair(tmp_path):
    p = tmp_path / "ok.yaml"
    p.write_text("k: v\n", encoding="utf-8")
    out = read_yaml(p)
    assert isinstance(out, tuple) and len(out) == 2


def test_read_yaml_missing_file_degrades(tmp_path):
    doc, err = read_yaml(tmp_path / "absent.yaml")
    assert doc is None
    assert isinstance(err, str) and err  # the reason travels to the caller


def test_read_yaml_malformed_degrades_not_raises(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("a: [unclosed\n  b: }{\n", encoding="utf-8")
    doc, err = read_yaml(p)
    assert doc is None
    assert isinstance(err, str) and err


def test_read_yaml_empty_file_degrades(tmp_path):
    p = tmp_path / "empty.yaml"
    p.write_text("", encoding="utf-8")
    doc, err = read_yaml(p)
    assert doc is None and isinstance(err, str)


def test_read_yaml_non_mapping_degrades(tmp_path):
    p = tmp_path / "list.yaml"
    p.write_text("- just\n- a\n- list\n", encoding="utf-8")
    doc, err = read_yaml(p)
    assert doc is None
    assert isinstance(err, str) and err


def test_read_yaml_non_utf8_degrades(tmp_path):
    p = tmp_path / "bin.yaml"
    p.write_bytes(b"a: \xff\xfe\x00binary\n")
    doc, err = read_yaml(p)
    assert doc is None
    assert isinstance(err, str) and err


def test_read_yaml_error_names_the_exception(tmp_path):
    doc, err = read_yaml(tmp_path / "absent.yaml")
    assert doc is None
    assert err.split(":", 1)[0] == "FileNotFoundError"


# ---------- atomic_write_text: the one write-guard face ----------

def test_atomic_write_roundtrips_bytes_and_unicode(tmp_path):
    p = tmp_path / "runs" / "state.json"
    payload = '{"ascii": 1, "unicode": "阈值 — ✓"}\n'
    atomic_write_text(p, payload)
    assert p.read_text(encoding="utf-8") == payload


def test_atomic_write_creates_missing_parents_nested(tmp_path):
    p = tmp_path / "a" / "b" / "c" / "deep.yaml"
    atomic_write_text(p, "k: v\n")
    assert p.read_text(encoding="utf-8") == "k: v\n"


def test_atomic_write_overwrites_existing_content(tmp_path):
    p = tmp_path / "ledger.jsonl"
    p.write_text("old\n", encoding="utf-8")
    atomic_write_text(p, "new\n")
    assert p.read_text(encoding="utf-8") == "new\n"


def test_atomic_write_leaves_no_tmp_residue(tmp_path):
    p = tmp_path / "runs" / "posteriors.yaml"
    atomic_write_text(p, "a: 1\n")
    siblings = [q.name for q in p.parent.iterdir()]
    assert not any(name.endswith(".tmp") for name in siblings)


def test_atomic_write_renames_within_the_same_directory(tmp_path, monkeypatch):
    """The atomicity guarantee is same-filesystem rename: the tmp file
    must be a sibling of the destination (a cross-directory rename can
    silently degrade to copy+delete on some platforms)."""
    import os as os_mod
    seen = []
    real_replace = os_mod.replace

    def spy(src, dst):
        seen.append((Path(src).parent, Path(dst).parent))
        return real_replace(src, dst)

    monkeypatch.setattr(os_mod, "replace", spy)
    p = tmp_path / "runs" / "x.json"
    atomic_write_text(p, "{}\n")
    assert seen == [(p.parent, p.parent)]


def test_atomic_write_accepts_str_path(tmp_path):
    p = tmp_path / "s.txt"
    atomic_write_text(str(p), "text")
    assert p.read_text(encoding="utf-8") == "text"


def test_atomic_write_returns_the_final_path(tmp_path):
    p = tmp_path / "ret.txt"
    assert atomic_write_text(p, "x") == p


# ---------- atomic_write_bytes + the unique/mode faces ----------

def test_atomic_write_bytes_roundtrips_binary(tmp_path):
    p = tmp_path / "bins" / "sample.bin"
    blob = b"MZ\x90\x00" + bytes(range(256))
    atomic_write_bytes(p, blob)
    assert p.read_bytes() == blob


def test_atomic_write_bytes_creates_parents_and_leaves_no_residue(tmp_path):
    p = tmp_path / "a" / "b" / "payload.bin"
    atomic_write_bytes(p, b"data")
    assert p.read_bytes() == b"data"
    assert not any(q.name.endswith(".tmp") for q in p.parent.iterdir())


def test_unique_write_never_shares_a_tmp_between_writers(tmp_path, monkeypatch):
    """Two writers writing the same destination concurrently must never
    share one tmp buffer (the two-writer tear). The unique face gives
    each call its own tmp name; the plain face is single-writer by
    contract and reuses one deterministic sibling."""
    import os as os_mod
    real_replace = os_mod.replace
    p = tmp_path / "q.json"

    # plain: deterministic sibling tmp — same name every call
    plain_names = []
    def plain_spy(src, dst):
        plain_names.append(Path(src).name)
        return real_replace(src, dst)
    monkeypatch.setattr(os_mod, "replace", plain_spy)
    atomic_write_text(p, "1")
    atomic_write_text(p, "2")
    assert len(set(plain_names)) == 1 and plain_names[0].endswith(".tmp")

    # unique: distinct tmp per call
    uniq_names = []
    def uniq_spy(src, dst):
        uniq_names.append(Path(src).name)
        return real_replace(src, dst)
    monkeypatch.setattr(os_mod, "replace", uniq_spy)
    atomic_write_text(p, "3", unique=True)
    atomic_write_text(p, "4", unique=True)
    assert len(uniq_names) == 2 and uniq_names[0] != uniq_names[1]
    assert all(n.endswith(".tmp") for n in uniq_names)
    assert p.read_text(encoding="utf-8") == "4"


def test_unique_write_tmp_is_a_sibling(tmp_path, monkeypatch):
    import os as os_mod
    seen = []
    real_replace = os_mod.replace

    def spy(src, dst):
        seen.append((Path(src).parent, Path(dst).parent))
        return real_replace(src, dst)

    monkeypatch.setattr(os_mod, "replace", spy)
    p = tmp_path / "runs" / "u.json"
    atomic_write_bytes(p, b"{}", unique=True)
    assert seen == [(p.parent, p.parent)]


def test_mode_parity_chmods_the_destination(tmp_path):
    p = tmp_path / "parity.json"
    atomic_write_text(p, "{}\n", unique=True, mode=0o644)
    assert (p.stat().st_mode & 0o777) == 0o644


def test_failed_replace_cleans_the_tmp(tmp_path, monkeypatch):
    """A write whose rename fails must not strand a tmp sibling (the
    non-silent cleanup discipline the unique-family callers pinned)."""
    import os as os_mod

    def boom(src, dst):
        raise OSError("disk on fire")

    monkeypatch.setattr(os_mod, "replace", boom)
    p = tmp_path / "stranded.json"
    with pytest.raises(OSError):
        atomic_write_text(p, "x", unique=True)
    assert not any(q.name.endswith(".tmp") for q in tmp_path.iterdir())
    with pytest.raises(OSError):
        atomic_write_text(p, "x")
    assert not any(q.name.endswith(".tmp") for q in tmp_path.iterdir())


# ---------- scripts_bootstrap ----------

def test_scripts_bootstrap_guard_inserts_scripts_dir_at_front(monkeypatch):
    """Absent from sys.path -> inserted at [0]; the (dir) Path is returned
    so migrated prologues keep their SCRIPT_DIR-style locals."""
    import sys as _sys
    import _common as _c
    scripts_dir = str(Path(_c.__file__).resolve().parent)
    monkeypatch.setattr(_sys, "path",
                        [p for p in _sys.path if p != scripts_dir])
    returned = scripts_bootstrap()
    assert _sys.path[0] == scripts_dir
    assert Path(returned) == Path(scripts_dir)


def test_scripts_bootstrap_is_idempotent_no_reorder(monkeypatch):
    """Already present -> strict no-op: no duplicate, no front-move. The
    guarded prologue every migrated call-site relied on (an unconditional
    insert would silently reorder twin resolution — the exact hazard the
    conftest session guard enforces)."""
    import sys as _sys
    import _common as _c
    scripts_dir = str(Path(_c.__file__).resolve().parent)
    fake = ["/aaa", scripts_dir, "/bbb"]
    monkeypatch.setattr(_sys, "path", list(fake))
    scripts_bootstrap()
    assert _sys.path == fake


def test_scripts_bootstrap_never_guesses_caller_depth(monkeypatch, tmp_path):
    """Anchored at _common's own directory — never the caller's parents.
    Called from a different cwd (tests/, a tool, anywhere) it still
    bootstraps exactly the scripts/ directory _common lives in."""
    import sys as _sys
    import _common as _c
    scripts_dir = str(Path(_c.__file__).resolve().parent)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(_sys, "path",
                        [p for p in _sys.path if p != scripts_dir])
    scripts_bootstrap()
    assert Path(_sys.path[0]) == Path(scripts_dir)


# ---------- leaf invariant: no repo imports ----------

def test_leaf_imports_no_repo_module():
    import _common as leaf
    src = Path(leaf.__file__).read_text(encoding="utf-8")
    assert "import yaml" in src or "from yaml" in src
    for banned in ("import kunglao", "from kunglao", "import rlvr",
                   "from rlvr", "import hooks", "from hooks",
                   "import harness_common", "from harness_common"):
        assert banned not in src, f"leaf imports repo module: {banned}"
