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

from _common import read_yaml, sha256_file, sha256_hex  # noqa: E402

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


# ---------- leaf invariant: no repo imports ----------

def test_leaf_imports_no_repo_module():
    import _common as leaf
    src = Path(leaf.__file__).read_text(encoding="utf-8")
    assert "import yaml" in src or "from yaml" in src
    for banned in ("import kunglao", "from kunglao", "import rlvr",
                   "from rlvr", "import hooks", "from hooks",
                   "import harness_common", "from harness_common"):
        assert banned not in src, f"leaf imports repo module: {banned}"
