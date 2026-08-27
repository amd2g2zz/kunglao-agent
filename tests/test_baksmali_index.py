# -*- coding: utf-8 -*-
"""TDD RED - baksmali_index DEX enumeration + xref (#670).

gitnexus is Java-only; for DEX we need baksmali. The output schema MUST be
shape-compatible with gitnexus so downstream consumers (anomaly detector
#663, hypothesis seeder #662) don't branch on tool identity.

Spec: openspec/changes/issue-670-mem-gated-jadx/specs/mem-gated-jadx/spec.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE.parent / "tools" / "static"))


class _FakeCP:
    """Mimics subprocess.CompletedProcess for monkeypatch."""
    def __init__(self, returncode, stdout, stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# ---------------------------------------------------------------------------
# RED1 - baksmali missing -> noop + warning, no crash
# ---------------------------------------------------------------------------

def test_red1_baksmali_missing_noop(tmp_path, monkeypatch):
    """baksmali binary not on PATH -> file written with classes=[],
    tool='baksmali', stderr warning, rc=0 (fail-open)."""
    from baksmali_index import run
    monkeypatch.setattr("shutil.which",
                        lambda n: None if n == "baksmali" else "/usr/bin/other")

    fake_apk = tmp_path / "x.apk"
    fake_apk.write_bytes(b"PK\x03\x04")

    rc = run(tmp_path, str(fake_apk))
    assert rc == 0, f"expected rc=0 fail-open, got {rc}"

    out = tmp_path / "evidence" / "smali_index.json"
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["tool"] == "baksmali"
    assert data["classes"] == []


# ---------------------------------------------------------------------------
# RED2 - schema shape
# ---------------------------------------------------------------------------

def test_red2_schema_shape(tmp_path, monkeypatch):
    """Output must carry tool, version, target, classes, scanned_at."""
    from baksmali_index import run

    fake_apk = tmp_path / "x.apk"
    fake_apk.write_bytes(b"PK\x03\x04")
    fake_classes = [
        {"name": "Lcom/x/A;", "methods": []},
    ]

    def fake_run(args, **kw):
        if "--version" in args:
            return _FakeCP(0, "baksmali 2.5.2")
        if "list" in args:
            return _FakeCP(0, json.dumps(fake_classes))
        return _FakeCP(0, json.dumps({"calls": [], "called_by": []}))
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/baksmali")
    monkeypatch.setattr("subprocess.run", fake_run)

    rc = run(tmp_path, str(fake_apk))
    assert rc == 0
    data = json.loads((tmp_path / "evidence" / "smali_index.json").read_text())
    for k in ("tool", "version", "target", "classes", "scanned_at"):
        assert k in data, f"missing top-level key: {k} in {data}"
    assert data["tool"] == "baksmali"
    assert data["version"] == "2.5.2"


# ---------------------------------------------------------------------------
# RED3 - gitnexus-shape compat (calls + called_by arrays)
# ---------------------------------------------------------------------------

def test_red3_gitnexus_shape_compat(tmp_path, monkeypatch):
    """Each method carries xrefs = {calls: [...], called_by: [...]}.
    Downstream consumers expect gitnexus-shape, so xrefs MUST be arrays
    (not dicts-of-dicts, not null)."""
    from baksmali_index import run, _xref_class

    fake_apk = tmp_path / "x.apk"
    fake_apk.write_bytes(b"PK\x03\x04")
    fake_list = [{"name": "Lcom/x/A;", "methods": []}]
    fake_xref = {"calls": ["Lcom/x/B;->b", "Lcom/x/C;->c"], "called_by": ["Lcom/x/Z;->z"]}

    def fake_run(args, **kw):
        if "--version" in args:
            return _FakeCP(0, "baksmali 2.5.2")
        if "list" in args:
            return _FakeCP(0, json.dumps(fake_list))
        if "xref" in args:
            return _FakeCP(0, json.dumps(fake_xref))
        return _FakeCP(1, "", "boom")
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/baksmali")
    monkeypatch.setattr("subprocess.run", fake_run)

    run(tmp_path, str(fake_apk))
    cls = {"name": "Lcom/x/A;", "methods": [{"name": "a", "signature": "()V"}]}
    _xref_class("/usr/bin/baksmali", cls)
    xrefs = cls["methods"][0]["xrefs"]
    assert isinstance(xrefs["calls"], list)
    assert isinstance(xrefs["called_by"], list)
    assert "Lcom/x/B;->b" in xrefs["calls"]


# ---------------------------------------------------------------------------
# RED4 - per-class xref fail-open
# ---------------------------------------------------------------------------

def test_red4_per_class_xref_fail_open(tmp_path, monkeypatch):
    """If xref fails for one class, that class's xrefs=[]; other classes
    unaffected. No crash."""
    from baksmali_index import _xref_class

    cls_a = {"name": "Lcom/A;", "methods": [{"name": "a", "signature": "()V"}]}
    cls_b = {"name": "Lcom/B;", "methods": [{"name": "b", "signature": "()V"}]}

    def fake_run(args, **kw):
        if "Lcom/A;" in args[-1]:
            return _FakeCP(1, "", "boom: class A xref failed")
        return _FakeCP(0, json.dumps({"calls": ["Lcom/B;->b"], "called_by": []}))
    monkeypatch.setattr("subprocess.run", fake_run)

    _xref_class("/usr/bin/baksmali", cls_a)
    _xref_class("/usr/bin/baksmali", cls_b)

    assert cls_a["methods"][0]["xrefs"] == {"calls": [], "called_by": []}
    assert "Lcom/B;->b" in cls_b["methods"][0]["xrefs"]["calls"]