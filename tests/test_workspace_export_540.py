# -*- coding: utf-8 -*-
"""tests/test_workspace_export_540.py — issue #540 export-tool locks.

Anchored surfaces:

1. scripts/kunglao_export.py exists and exposes classify / build_manifest /
   export_workspace / verify_manifest (the public surface used by external
   callers; locks against silent renaming).
2. Zone classifier routes:
   - carriers (CLAUDE.md, _INDEX, .workspace-manifest.json, .mcp.json,
     .convergence_ledger, template_version.json, register.yaml) -> "carrier"
   - evidence dir + .pcap/.frida/.json/.md/.yaml under any path -> "evidence"
   - scratch/ / tmp/ / .cache/ -> "scratch" (excluded by default)
   - .git/ is always skipped (workspace-external)
3. Export/verify roundtrip: tar.gz produced by export_workspace is
   verifiable end-to-end; a tampered file fails verify.
4. Default export excludes scratch; --include-scratch bundles it under its
   own zone and verify then walks it too.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "kunglao_export.py"


def _load():
    name = "kunglao_export_540"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# =====================================================================
# 1 — script exists, public surface is stable
# =====================================================================

def test_export_script_exists():
    assert SCRIPT.is_file(), (
        f"{SCRIPT} missing; #540 workspace export tool surface")


def test_public_surface_intact():
    mod = _load()
    for sym in ("classify", "build_manifest", "export_workspace",
                "verify_manifest", "MANIFEST_VERSION",
                "CARRIER_PATTERNS", "SCRATCH_PATTERNS"):
        assert hasattr(mod, sym), f"kunglao_export.py missing {sym!r}"


def test_manifest_version_pinned():
    """#540 pairs with #536 version-stamp system; pin the manifest version."""
    mod = _load()
    assert isinstance(mod.MANIFEST_VERSION, str)
    assert mod.MANIFEST_VERSION, "MANIFEST_VERSION must not be empty"


# =====================================================================
# 2 — zone classifier routing
# =====================================================================

CARRIER_CASES = (
    "CLAUDE.md",
    ".mcp.json",
    ".env.example",
    ".convergence_ledger",
    "task_spec_snapshot.yaml",
    "notes/_INDEX",
    ".workspace-manifest.json",
    "template_version.json",
    "register.yaml",
)

EVIDENCE_CASES = (
    "evidence/sample.pcap",
    "evidence/capture.json",
    "runs/agent.frida.js",
    "evidence/note.md",
    "runs/state.yaml",
    ".fact/F001.json",
)

SCRATCH_CASES = (
    "scratch/scratch.py",
    "scratch/nested/FINDINGS.md",
    "tmp/cache.bin",
    ".cache/ty/0",
)


@pytest.mark.parametrize("rel", CARRIER_CASES)
def test_classify_carrier(rel):
    mod = _load()
    assert mod.classify(Path(rel)) == "carrier", (
        f"{rel!r} expected carrier zone (got other)")


@pytest.mark.parametrize("rel", EVIDENCE_CASES)
def test_classify_evidence(rel):
    mod = _load()
    assert mod.classify(Path(rel)) == "evidence", (
        f"{rel!r} expected evidence zone")


@pytest.mark.parametrize("rel", SCRATCH_CASES)
def test_classify_scratch(rel):
    mod = _load()
    assert mod.classify(Path(rel)) == "scratch", (
        f"{rel!r} expected scratch zone (excluded by default)")


def test_classify_unknown_returns_other(tmp_path):
    mod = _load()
    p = tmp_path / "weird.bin"
    p.write_bytes(b"")
    assert mod.classify(p) == "other"


# =====================================================================
# 3 — build_manifest: skip .git, route files, sha256 deterministic
# =====================================================================

def test_manifest_skips_git_dir(tmp_path):
    mod = _load()
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "CLAUDE.md").write_text("c\n", encoding="utf-8")
    (ws / ".git").mkdir()
    (ws / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    m = mod.build_manifest(ws, include_scratch=False)
    paths = {e["path"] for e in m["zones"]["carrier"]}
    assert ".git/HEAD" not in paths, "build_manifest must skip .git"
    assert "CLAUDE.md" in paths


def test_manifest_has_expected_zones(tmp_path):
    mod = _load()
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "CLAUDE.md").write_text("c\n", encoding="utf-8")
    (ws / "evidence").mkdir()
    (ws / "evidence" / "c.pcap").write_bytes(b"\xd4\xc3\xb2\xa1")
    (ws / "scratch").mkdir()
    (ws / "scratch" / "scratch.py").write_text("# scratch\n", encoding="utf-8")
    m = mod.build_manifest(ws, include_scratch=False)
    assert set(m["zones"].keys()) >= {"carrier", "evidence", "scratch", "other"}
    # scratch excluded by default
    assert m["zones"]["scratch"] == [], "scratch leaked into default manifest"


def test_manifest_excludes_scratch_unless_requested(tmp_path):
    mod = _load()
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "scratch").mkdir()
    (ws / "scratch" / "f.txt").write_text("s\n", encoding="utf-8")
    m_default = mod.build_manifest(ws, include_scratch=False)
    m_full = mod.build_manifest(ws, include_scratch=True)
    assert m_default["zones"]["scratch"] == []
    assert any(e["path"] == "scratch/f.txt" for e in m_full["zones"]["scratch"])


# #687 ruling: the fixture must pin exact on-disk bytes via write_bytes.
# write_text(newline=None) translates \n to os.linesep, so on Windows the
# disk bytes were b'{"x": 1}\r\n' while the old expectation hardcoded the
# LF digest — a platform-brittle expectation, not a production defect
# (sha256_file reads "rb"; roundtrip/tamper tests prove end-to-end
# consistency over actual bytes).
_SHA_FIXTURE_CASES = (
    b'{"x": 1}\n',       # LF — historical fixture content
    b'{"x": 1}\r\n',     # CRLF — actual Windows write_text bytes; locks
                         # "hash actual bytes, never normalized text"
)


@pytest.mark.parametrize("on_disk_bytes", _SHA_FIXTURE_CASES,
                         ids=["lf", "crlf"])
def test_manifest_sha256_is_actual(tmp_path, on_disk_bytes):
    mod = _load()
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / ".mcp.json").write_bytes(on_disk_bytes)
    m = mod.build_manifest(ws, include_scratch=False)
    entries = m["zones"]["carrier"]
    assert entries, "carrier zone empty"
    # expectation derived from the input bytes (numeric-fidelity: the
    # digest is computed from the same literal that wrote the file —
    # no second hardcoded hash)
    import hashlib
    expected = hashlib.sha256(on_disk_bytes).hexdigest()
    assert entries[0]["sha256"] == expected


# =====================================================================
# 4 — export / verify roundtrip
# =====================================================================

def _materialize_minimal_ws(ws: Path):
    """Materialize a small workspace covering all three zones + .git noise."""
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "CLAUDE.md").write_text("# project\n", encoding="utf-8")
    (ws / ".workspace-manifest.json").write_text(
        '{"schema_rev": "v1", "carriers": []}\n', encoding="utf-8")
    (ws / "evidence").mkdir(exist_ok=True)
    (ws / "evidence" / "run.json").write_text('{"ok": true}\n',
                                              encoding="utf-8")
    (ws / "scratch").mkdir(exist_ok=True)
    (ws / "scratch" / "explore.py").write_text("print('hi')\n",
                                               encoding="utf-8")
    (ws / ".git").mkdir(exist_ok=True)
    (ws / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")


def test_export_verify_roundtrip_default(tmp_path):
    mod = _load()
    ws = tmp_path / "ws"
    _materialize_minimal_ws(ws)
    arc = tmp_path / "out.tar.gz"
    rc = mod.export_workspace(ws, arc, include_scratch=False)
    assert rc == 0
    assert arc.is_file()
    # tarball structure
    with tarfile.open(arc, "r:gz") as tar:
        names = tar.getnames()
        assert "MANIFEST.json" in names
        assert "export/CLAUDE.md" in names
        assert "export/evidence/run.json" in names
        assert "export/scratch/explore.py" not in names  # excluded by default
        manifest_bytes = tar.extractfile("MANIFEST.json").read()
    manifest = json.loads(manifest_bytes)
    assert manifest["include_scratch"] is False
    # verify: default excludes scratch → scratch entries skipped
    rc2 = mod.verify_manifest(arc)
    assert rc2 == 0, "roundtrip verify failed"


def test_export_verify_roundtrip_include_scratch(tmp_path):
    mod = _load()
    ws = tmp_path / "ws"
    _materialize_minimal_ws(ws)
    arc = tmp_path / "out.tar.gz"
    rc = mod.export_workspace(ws, arc, include_scratch=True)
    assert rc == 0
    with tarfile.open(arc, "r:gz") as tar:
        names = tar.getnames()
        assert "export/scratch/explore.py" in names
        manifest_bytes = tar.extractfile("MANIFEST.json").read()
    manifest = json.loads(manifest_bytes)
    assert manifest["include_scratch"] is True
    # verify with --include-scratch context (manifest already records True)
    rc2 = mod.verify_manifest(arc)
    assert rc2 == 0


def test_verify_detects_tampered_file(tmp_path):
    mod = _load()
    ws = tmp_path / "ws"
    _materialize_minimal_ws(ws)
    arc = tmp_path / "out.tar.gz"
    rc = mod.export_workspace(ws, arc, include_scratch=False)
    assert rc == 0
    # Tamper: rebuild the archive with a corrupted CLAUDE.md
    import io
    import shutil
    tampered = tmp_path / "tampered.tar.gz"
    with tarfile.open(arc, "r:gz") as src, \
         tarfile.open(tampered, "w:gz") as dst:
        manifest_bytes = src.extractfile("MANIFEST.json").read()
        for m in src.getmembers():
            if m.name == "export/CLAUDE.md":
                bad = b"# tampered\n"
                info = tarfile.TarInfo(m.name)
                info.size = len(bad)
                dst.addfile(info, io.BytesIO(bad))
            elif m.name == "MANIFEST.json":
                info = tarfile.TarInfo(m.name)
                info.size = len(manifest_bytes)
                dst.addfile(info, io.BytesIO(manifest_bytes))
            else:
                data = src.extractfile(m).read()
                info = tarfile.TarInfo(m.name)
                info.size = len(data)
                dst.addfile(info, io.BytesIO(data))
    rc2 = mod.verify_manifest(tampered)
    assert rc2 == 1, "verify must FAIL when a file's sha256 doesn't match manifest"


def test_export_missing_workspace(tmp_path):
    mod = _load()
    arc = tmp_path / "out.tar.gz"
    rc = mod.export_workspace(tmp_path / "does-not-exist", arc,
                              include_scratch=False)
    assert rc == 1, "missing workspace must exit non-zero"
