# -*- coding: utf-8 -*-
"""TDD RED - apk_mem_gate memory-aware dispatch estimator (#670).

Calibration: 395MB APK, 12GB heap, ~10h GC-thrashed completion ->
  est = max(4GB, 50 * dex_bytes_total)
  budget = 0.65 * avail_gb
  verdict = jadx-ok (budget >= 1.5*est) | targeted-jadx | smali-only | refuse (JAR)

Spec: openspec/changes/issue-670-mem-gated-jadx/specs/mem-gated-jadx/spec.md
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path


_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE.parent / "tools" / "static"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_apk(tmp_path: Path, dex_files: dict) -> Path:
    """Create a synthetic APK with the named dex files + given sizes."""
    apk = tmp_path / "fake.apk"
    with zipfile.ZipFile(apk, "w") as zf:
        for name, data in dex_files.items():
            zf.writestr(name, data)
    return apk


def _make_jar(tmp_path: Path, size_bytes: int = 1024) -> Path:
    """Create a synthetic JAR (just a ZIP with one entry)."""
    jar = tmp_path / "fake.jar"
    with zipfile.ZipFile(jar, "w") as zf:
        zf.writestr("Main.class", b"\x00" * size_bytes)
    return jar


# ---------------------------------------------------------------------------
# RED1 - small APK + plenty memory -> jadx-ok
# ---------------------------------------------------------------------------

def test_red1_small_apk_jadx_ok(tmp_path, monkeypatch):
    """1MB dex + 9.5GB avail -> est=4GB (floor), budget=6.175GB,
    budget >= 1.5*est (6.175 >= 6) -> jadx-ok."""
    from apk_mem_gate import run
    monkeypatch.setattr("apk_mem_gate._avail_gb", lambda: 9.5)
    apk = _make_apk(tmp_path, {"classes.dex": b"\x00" * (1 * 1024 * 1024)})
    rc = run(tmp_path, str(apk))
    assert rc == 0
    data = json.loads((tmp_path / "evidence" / "apk_mem_gate.json").read_text())
    assert data["verdict"] == "jadx-ok", data


# ---------------------------------------------------------------------------
# RED2 - large APK + tight memory -> smali-only
# ---------------------------------------------------------------------------

def test_red2_large_apk_smalionly(tmp_path, monkeypatch):
    """50MB dex + 1GB avail -> est = max(4, 50*50M/1G) = 4GB (floor).
    budget = 0.65 * 1 = 0.65GB. budget (0.65) < est (4) -> smali-only."""
    from apk_mem_gate import run
    monkeypatch.setattr("apk_mem_gate._avail_gb", lambda: 1.0)
    apk = _make_apk(tmp_path, {"classes.dex": b"\x00" * (50 * 1024 * 1024)})
    rc = run(tmp_path, str(apk))
    assert rc == 0
    data = json.loads((tmp_path / "evidence" / "apk_mem_gate.json").read_text())
    assert data["verdict"] == "smali-only", data


# ---------------------------------------------------------------------------
# RED3 - medium APK + marginal memory -> targeted-jadx
# ---------------------------------------------------------------------------

def test_red3_medium_apk_targeted_jadx(tmp_path, monkeypatch):
    """90MB dex + 7.5GB avail -> est = max(4, 50*90M/1G) = 4.5GB.
    budget = 0.65 * 7.5 = 4.875GB. est <= budget (4.5 <= 4.875) AND
    budget < 1.5*est (4.875 < 6.75) -> targeted-jadx."""
    from apk_mem_gate import run
    monkeypatch.setattr("apk_mem_gate._avail_gb", lambda: 7.5)
    apk = _make_apk(tmp_path, {"classes.dex": b"\x00" * (90 * 1024 * 1024)})
    rc = run(tmp_path, str(apk))
    data = json.loads((tmp_path / "evidence" / "apk_mem_gate.json").read_text())
    assert data["verdict"] == "targeted-jadx", data


# ---------------------------------------------------------------------------
# RED4 - JAR -> refuse regardless of memory
# ---------------------------------------------------------------------------

def test_red4_jar_always_refuse(tmp_path, monkeypatch):
    """JAR target -> refuse with explicit reason, even with 100GB avail."""
    from apk_mem_gate import run
    monkeypatch.setattr("apk_mem_gate._avail_gb", lambda: 100.0)
    jar = _make_jar(tmp_path, 1024)
    rc = run(tmp_path, str(jar))
    data = json.loads((tmp_path / "evidence" / "apk_mem_gate.json").read_text())
    assert data["verdict"] == "refuse", data
    assert "no smali fallback" in data["reason"].lower(), data
    assert data["target_ext"] == ".jar"


# ---------------------------------------------------------------------------
# RED5 - dex_bytes_total = sum of dex file sizes (not zip overhead)
# ---------------------------------------------------------------------------

def test_red5_dex_bytes_total_sums_dex_sizes(tmp_path, monkeypatch):
    """dex_bytes_total must be sum of uncompressed dex sizes inside the APK,
    not the .apk file size (which includes zip overhead + non-dex entries)."""
    from apk_mem_gate import run
    monkeypatch.setattr("apk_mem_gate._avail_gb", lambda: 100.0)
    apk = _make_apk(tmp_path, {
        "classes.dex": b"\x00" * (1 * 1024 * 1024),
        "classes2.dex": b"\x00" * (2 * 1024 * 1024),
        "classes3.dex": b"\x00" * (3 * 1024 * 1024),
        "AndroidManifest.xml": b"<?xml" * 100,
    })
    rc = run(tmp_path, str(apk))
    data = json.loads((tmp_path / "evidence" / "apk_mem_gate.json").read_text())
    assert data["dex_count"] == 3, data
    assert data["dex_bytes_total"] == 6 * 1024 * 1024, data
    assert data["apk_size"] > data["dex_bytes_total"], data


# ---------------------------------------------------------------------------
# RED6 - avail_gb fallback when detection fails
# ---------------------------------------------------------------------------

def test_red6_avail_gb_fallback(tmp_path, monkeypatch):
    """When the stdlib mem detection raises (e.g., ctypes on locked-down env),
    _avail_gb must return a positive fallback (4 GB) rather than 0."""
    from apk_mem_gate import _avail_gb
    monkeypatch.setattr("apk_mem_gate._mem_posix",
                        lambda: (_ for _ in ()).throw(OSError("locked")))
    monkeypatch.setattr("apk_mem_gate._mem_windows",
                        lambda: (_ for _ in ()).throw(OSError("locked")))
    val = _avail_gb()
    assert val > 0, f"avail_gb must be > 0 even on detection failure, got {val}"


# ---------------------------------------------------------------------------
# RED7 - calibration_basis always populated
# ---------------------------------------------------------------------------

def test_red7_calibration_basis_always_present(tmp_path, monkeypatch):
    """calibration_basis MUST be non-empty in every verdict path."""
    from apk_mem_gate import run
    monkeypatch.setattr("apk_mem_gate._avail_gb", lambda: 8.0)
    apk = _make_apk(tmp_path, {"classes.dex": b"\x00" * (1024)})
    run(tmp_path, str(apk))
    data = json.loads((tmp_path / "evidence" / "apk_mem_gate.json").read_text())
    assert "calibration_basis" in data and data["calibration_basis"], data
    assert "single data point" in data["calibration_basis"].lower(), data


# ---------------------------------------------------------------------------
# RED8 - evidence JSON written even on REFUSE
# ---------------------------------------------------------------------------

def test_red8_evidence_written_on_refuse(tmp_path, monkeypatch):
    """REFUSE verdict MUST still write evidence/apk_mem_gate.json."""
    from apk_mem_gate import run
    monkeypatch.setattr("apk_mem_gate._avail_gb", lambda: 100.0)
    jar = _make_jar(tmp_path)
    run(tmp_path, str(jar))
    assert (tmp_path / "evidence" / "apk_mem_gate.json").exists()
    data = json.loads((tmp_path / "evidence" / "apk_mem_gate.json").read_text())
    assert data["verdict"] == "refuse"


# ---------------------------------------------------------------------------
# RED8b - operator override apk_mem_override=jadx
# ---------------------------------------------------------------------------

def test_red8b_operator_override_jadx(tmp_path, monkeypatch):
    """apk_mem_override=jadx forces jadx-ok regardless of memory math."""
    from apk_mem_gate import run
    monkeypatch.setattr("apk_mem_gate._avail_gb", lambda: 0.1)
    (tmp_path / "analysis_state.txt").write_text("apk_mem_override=jadx\n")
    apk = _make_apk(tmp_path, {"classes.dex": b"\x00" * (1024 * 1024)})
    run(tmp_path, str(apk))
    data = json.loads((tmp_path / "evidence" / "apk_mem_gate.json").read_text())
    assert data["verdict"] == "jadx-ok"
    assert "override" in data["calibration_basis"].lower()