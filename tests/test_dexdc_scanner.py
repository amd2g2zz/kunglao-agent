# -*- coding: utf-8 -*-
"""RED tests for issue #692 WP2 — dex-decompiler provider wrapper.

Pins tools/static/dexdc_scanner.py (design D6):

- detection: PyO3 wheel (`import dex_decompiler`) FIRST, then the
  `dex-decompile` CLI; neither -> status `unavailable` evidence + exit 0
  (fail-open, never raises) — the #669/#670 wrapper posture.
- index mode: evidence/dexdc_index.json in the #670 gitnexus-shape wire
  ({tool, version, target, classes[].methods[].xrefs{calls,called_by},
  scanned_at}) plus per-method cfg (nodes/edges) as the dexdc value-add.
- taint mode: evidence/dexdc_taint.json carrying the upstream IssueReport
  face ({tool, status, target, seeds, issues[].{rule,source,sink,traces},
  count, scanned_at}).

Upstream facts pinned here (github.com/androguard/dex-decompiler README):
  pyo3: dex_decompiler.parse_dex(bytes); dex.get_method_bytecode_and_cfg(
        "com.example.Main", "onCreate") -> (rows, cfg_nodes, cfg_edges)
  cli:  dex-decompile -i target --taint-solve --taint-output issues.json
        --taint-api <seed> (repeatable), --only-package, -d out/

Landing-checklist asserts (#680 pattern): release-manifest asset declared,
tools/_INDEX.yaml dexdc provider entry (D0 matrix coverage), toolchain
FIXES["dexdc"] ToolMeta with the official URL, UTF-8 stdout guard.

RED phase: tools/static/dexdc_scanner.py does not exist.
"""
from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TOOLS_STATIC = REPO / "tools" / "static"
sys.path.insert(0, str(TOOLS_STATIC))


# ---------- fake plumbing ----------

class _FakeCP:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


def _no_binding(monkeypatch):
    monkeypatch.setattr(importlib, "import_module",
                        lambda name: (_ for _ in ()).throw(
                            ImportError(name)))
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: None)


# ---------- RED1: fail-open when no wheel and no CLI ----------

def test_red1_unavailable_writes_both_evidence_and_exits_zero(
        tmp_path, monkeypatch):
    import dexdc_scanner as ds
    _no_binding(monkeypatch)
    fake_apk = tmp_path / "x.apk"
    fake_apk.write_bytes(b"PK\x03\x04")

    rc = ds.run(tmp_path, str(fake_apk), mode="both")

    assert rc == 0
    idx = json.loads((tmp_path / "evidence" / "dexdc_index.json")
                     .read_text(encoding="utf-8"))
    tnt = json.loads((tmp_path / "evidence" / "dexdc_taint.json")
                     .read_text(encoding="utf-8"))
    assert idx["status"] == "unavailable"
    assert tnt["status"] == "unavailable"
    assert idx["tool"] == "dexdc" and tnt["tool"] == "dexdc"


# ---------- RED2: index schema is the gitnexus-shape wire ----------

def _fake_pyo3(monkeypatch, cfg_rows=(), nodes=(), edges=()):
    """A dex_decompiler module stub with ONLY the documented surface."""
    fake = types.ModuleType("dex_decompiler")
    fake.__version__ = "0.1.0-test"

    class _Dex:
        def get_method_bytecode_and_cfg(self, cls, method):
            return (list(cfg_rows), list(nodes), list(edges))

        def decompile_to_dir(self, out):
            return None

    def parse_dex(data):
        return _Dex()

    fake.parse_dex = parse_dex
    monkeypatch.setattr(importlib, "import_module", lambda name: fake)
    return fake


def test_red2_index_schema_gitnexus_shape(tmp_path, monkeypatch):
    import dexdc_scanner as ds
    _fake_pyo3(monkeypatch,
               nodes=["n0", "n1"],
               edges=[["n0", "n1"]])
    fake_apk = tmp_path / "x.apk"
    fake_apk.write_bytes(b"PK\x03\x04")

    rc = ds.run(tmp_path, str(fake_apk), mode="index",
                methods=[("com.example.Main", "onCreate")])

    assert rc == 0
    idx = json.loads((tmp_path / "evidence" / "dexdc_index.json")
                     .read_text(encoding="utf-8"))
    # the #670 wire keys, exactly
    for key in ("tool", "version", "target", "classes", "scanned_at"):
        assert key in idx, f"missing wire key {key}"
    assert idx["status"] == "ok"
    assert idx["face"] == "pyo3"
    cls = idx["classes"][0]
    assert cls["name"] == "com.example.Main"
    m = cls["methods"][0]
    assert m["name"] == "onCreate"
    assert set(m["xrefs"]) == {"calls", "called_by"}
    assert m["cfg"]["nodes"] == ["n0", "n1"]
    assert m["cfg"]["edges"] == [["n0", "n1"]]


def test_red2b_pyo3_face_wins_cli_never_spawned(tmp_path, monkeypatch):
    import dexdc_scanner as ds
    import subprocess
    _fake_pyo3(monkeypatch)
    spawned = []
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: spawned.append(a) or _FakeCP())
    fake_apk = tmp_path / "x.apk"
    fake_apk.write_bytes(b"PK\x03\x04")

    ds.run(tmp_path, str(fake_apk), mode="index",
           methods=[("com.example.Main", "onCreate")])
    assert spawned == [], "pyo3 face available -> CLI must not spawn"


# ---------- RED3: taint schema (CLI face, IssueReport normalization) ----------

def test_red3_taint_schema_from_cli_issue_report(tmp_path, monkeypatch):
    import dexdc_scanner as ds
    import shutil
    import subprocess
    fake = types.ModuleType("dex_decompiler")
    monkeypatch.setattr(importlib, "import_module",
                        lambda name: (_ for _ in ()).throw(
                            ImportError(name)))
    monkeypatch.setattr(shutil, "which",
                        lambda n: "/usr/bin/dex-decompile" if n ==
                        "dex-decompile" else None)

    issue_report = {"issues": [{"rule": "location-leak",
                                "source": "getLastLocation",
                                "sink": "Landroid/util/Log;->d",
                                "traces": [["b0", "b1"]]}]}
    captured = {}

    def fake_run(args, **kw):
        captured["args"] = args
        # the CLI writes the IssueReport file itself; mirror that
        for i, a in enumerate(args):
            if a == "--taint-output":
                Path(args[i + 1]).write_text(
                    json.dumps(issue_report), encoding="utf-8")
        return _FakeCP(0, "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    fake_apk = tmp_path / "x.apk"
    fake_apk.write_bytes(b"PK\x03\x04")

    rc = ds.run(tmp_path, str(fake_apk), mode="taint",
                seeds=["getDeviceId", "getLastLocation"])

    assert rc == 0
    assert "--taint-solve" in captured["args"]
    tnt = json.loads((tmp_path / "evidence" / "dexdc_taint.json")
                     .read_text(encoding="utf-8"))
    assert tnt["status"] == "ok"
    assert tnt["face"] == "cli"
    assert tnt["seeds"] == ["getDeviceId", "getLastLocation"]
    assert tnt["count"] == 1
    issue = tnt["issues"][0]
    for key in ("rule", "source", "sink", "traces"):
        assert key in issue
    assert issue["source"] == "getLastLocation"


# ---------- RED4: landing checklist (#680 pattern) ----------

def test_red4_release_manifest_declares_dexdc_scanner():
    text = (REPO / "release-manifest.yaml").read_text(encoding="utf-8")
    assert "tools/static/dexdc_scanner.py" in text


def test_red4b_index_registers_dexdc_provider_and_covers_matrix():
    import yaml
    data = yaml.safe_load((REPO / "tools" / "_INDEX.yaml")
                          .read_text(encoding="utf-8"))
    providers = {t.get("provider") for t in data["tools"] if t.get("provider")}
    assert "dexdc" in providers
    produced = set()
    for t in data["tools"]:
        produced.update(t.get("produces") or [])
    matrix = {
        "android:java-source", "android:call-graph", "android:data-flow",
        "android:string-decrypt", "android:algorithm-verify",
        "android:semantic-query", "android:dex-rewrite",
        "android:bytecode-truth",
    }
    assert matrix <= produced, f"matrix gaps: {matrix - produced}"


def test_red4c_toolchain_fixes_dexdc_toolmeta_official_url():
    sys.path.insert(0, str(REPO / "scripts"))
    import toolchain
    meta = toolchain.FIXES.get("dexdc")
    assert meta is not None, "FIXES['dexdc'] ToolMeta missing"
    assert meta.url == "https://github.com/androguard/dex-decompiler"
    assert meta.description
    assert "dex_decompiler" in meta.fix  # the wheel/module face in guidance
    na = toolchain._STATIC_NEXT_ACTIONS.get("dexdc")
    assert na is not None and na.action == "install"


def test_red4d_utf8_stdout_guard_present():
    src = (TOOLS_STATIC / "dexdc_scanner.py").read_text(encoding="utf-8")
    assert "reconfigure" in src and "utf-8" in src


def test_red4e_static_index_catalog_row():
    text = (REPO / "tools" / "_index-static.md").read_text(encoding="utf-8")
    assert "dexdc-decompile" in text
