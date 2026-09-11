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
import os
import sys
import zipfile
from pathlib import Path

import pytest


_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE.parent / "tools" / "static"))


GB = 1024 ** 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _raises(exc: Exception):
    """A zero-arg callable that raises `exc` (a dead platform probe)."""
    def _boom():
        raise exc
    return _boom


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
    monkeypatch.setattr("apk_mem_gate._avail_probe",
                        lambda: (9.5, "ok", ""))
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
    monkeypatch.setattr("apk_mem_gate._avail_probe",
                        lambda: (1.0, "ok", ""))
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
    monkeypatch.setattr("apk_mem_gate._avail_probe",
                        lambda: (7.5, "ok", ""))
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
    monkeypatch.setattr("apk_mem_gate._avail_probe",
                        lambda: (100.0, "ok", ""))
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
    monkeypatch.setattr("apk_mem_gate._avail_probe",
                        lambda: (100.0, "ok", ""))
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
    """When the platform mem detection raises (e.g., ctypes on a locked-down
    env), _avail_gb must return the 4 GB floor rather than 0 — on EVERY
    platform, darwin included (the dead probe issue 223 fixed) — and the
    fallback must be marked as such."""
    import apk_mem_gate as g
    for probe in ("_mem_posix", "_mem_windows", "_mem_darwin"):
        monkeypatch.setattr(f"apk_mem_gate.{probe}", _raises(OSError("locked")))
    val = g._avail_gb()
    assert val == g.DEFAULTS["apk_mem_floor_gb"], val
    assert g._avail_probe() == (g.DEFAULTS["apk_mem_floor_gb"],
                                "floor-fallback", "OSError: locked")


# ---------------------------------------------------------------------------
# RED7 - calibration_basis always populated
# ---------------------------------------------------------------------------

def test_red7_calibration_basis_always_present(tmp_path, monkeypatch):
    """calibration_basis MUST be non-empty in every verdict path."""
    from apk_mem_gate import run
    monkeypatch.setattr("apk_mem_gate._avail_probe",
                        lambda: (8.0, "ok", ""))
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
    monkeypatch.setattr("apk_mem_gate._avail_probe",
                        lambda: (100.0, "ok", ""))
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
    monkeypatch.setattr("apk_mem_gate._avail_probe",
                        lambda: (0.1, "ok", ""))
    (tmp_path / "analysis_state.txt").write_text("apk_mem_override=jadx\n")
    apk = _make_apk(tmp_path, {"classes.dex": b"\x00" * (1024 * 1024)})
    run(tmp_path, str(apk))
    data = json.loads((tmp_path / "evidence" / "apk_mem_gate.json").read_text())
    assert data["verdict"] == "jadx-ok"
    assert "override" in data["calibration_basis"].lower()


# ---------------------------------------------------------------------------
# RED9 - darwin probe (issue 223): SC_AVPHYS_PAGES is a Linux-only key
# ---------------------------------------------------------------------------
#
# Field pathology (owner macOS host): `_mem_posix` raised
# `ValueError: unrecognized configuration name` on darwin, `_avail_gb`
# swallowed it and returned the 4 GB floor -> budget = 0.65 x 4 = 2.6 GB,
# a constant below every est -> jadx blocked for every APK on every Mac.
# On darwin the probe reads the Mach VM counters instead.

def test_darwin_dispatch_measures_not_the_sysconf_floor(monkeypatch):
    """Review scenario: platform=darwin + the Linux-only sysconf key
    unavailable -> MEASURE through the Mach counters, never the floor."""
    import apk_mem_gate as g
    page = os.sysconf("SC_PAGESIZE")
    with monkeypatch.context() as mp:
        mp.setattr(sys, "platform", "darwin")
        mp.setattr(g, "_mem_posix",
                   _raises(ValueError("unrecognized configuration name")))
        mp.setattr(g, "_darwin_vm_page_counts", lambda: (1000, 2000, 3000),
                   raising=False)
        assert g._avail_gb() == (6000 * page) / GB, \
            "darwin must measure, not floor"
        assert g._avail_gb() != g.DEFAULTS["apk_mem_floor_gb"]
        assert g._avail_probe() == ((6000 * page) / GB, "ok", "")


def test_mem_darwin_sums_free_inactive_speculative_pages(monkeypatch):
    """available = (free + inactive + speculative) pages x page size."""
    import apk_mem_gate as g
    page = os.sysconf("SC_PAGESIZE")
    monkeypatch.setattr(g, "_darwin_vm_page_counts", lambda: (11, 22, 33))
    assert g._mem_darwin() == float((11 + 22 + 33) * page)


def test_linux_probe_path_unchanged(monkeypatch):
    """Non-darwin dispatch still runs the sysconf probe, unmodified."""
    import apk_mem_gate as g
    with monkeypatch.context() as mp:
        mp.setattr(sys, "platform", "linux")
        mp.setattr(g, "_mem_posix", lambda: 8 * GB)
        mp.setattr(g, "_mem_darwin",
                   _raises(AssertionError("darwin probe ran on linux")),
                   raising=False)
        assert g._avail_gb() == 8.0
        assert g._avail_probe() == (8.0, "ok", "")


def test_windows_probe_path_unchanged(monkeypatch):
    """Windows dispatch still runs GlobalMemoryStatusEx, unmodified."""
    import apk_mem_gate as g
    with monkeypatch.context() as mp:
        mp.setattr(sys, "platform", "win32")
        mp.setattr(g, "_mem_windows", lambda: 16 * GB)
        mp.setattr(g, "_mem_posix",
                   _raises(AssertionError("posix probe ran on windows")))
        assert g._avail_gb() == 16.0
        assert g._avail_probe() == (16.0, "ok", "")


def test_probe_failure_floors_but_is_marked_in_the_verdict(
        tmp_path, monkeypatch):
    """A dead probe stays fail-safe AND visible: the floor plus a marker
    that distinguishes it from a genuinely-4GB host."""
    import apk_mem_gate as g
    from apk_mem_gate import run
    monkeypatch.setattr(g, "_probe_avail_bytes",
                        _raises(OSError("no Mach counters")))
    apk = _make_apk(tmp_path, {"classes.dex": b"\x00" * (1024 * 1024)})
    run(tmp_path, str(apk))

    assert g._avail_gb() == g.DEFAULTS["apk_mem_floor_gb"]
    data = json.loads((tmp_path / "evidence" / "apk_mem_gate.json").read_text())
    assert data["avail_gb"] == 4.0
    assert data["avail_probe"] == "floor-fallback", data
    assert "avail_probe: floor-fallback" in data["reason"], data
    assert "no Mach counters" in data["reason"], data


def test_measured_probe_leaves_no_fallback_note(tmp_path, monkeypatch):
    """The marker is failure-only: a measured host keeps reason clean."""
    import apk_mem_gate as g
    from apk_mem_gate import run
    monkeypatch.setattr(g, "_avail_probe", lambda: (9.5, "ok", ""))
    apk = _make_apk(tmp_path, {"classes.dex": b"\x00" * (1024 * 1024)})
    run(tmp_path, str(apk))
    data = json.loads((tmp_path / "evidence" / "apk_mem_gate.json").read_text())
    assert data["avail_probe"] == "ok", data
    assert data["reason"] == "", data


def test_cli_stdout_carries_the_marker_for_the_env_fact(
        tmp_path, monkeypatch, capsys):
    """The issue 215 recorder mirrors the ONE stdout line into env-facts:
    the fallback marker must travel on it (avail_probe + reason), not die
    at the tool boundary."""
    import apk_mem_gate as g
    monkeypatch.setattr(g, "_probe_avail_bytes", _raises(OSError("probe dead")))
    apk = _make_apk(tmp_path, {"classes.dex": b"\x00" * (1024 * 1024)})
    assert g.main([str(tmp_path), str(apk)]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["verdict"] == "smali-only", out
    assert out["avail_probe"] == "floor-fallback", out
    assert "avail_probe: floor-fallback" in out["reason"], out


@pytest.mark.skipif(sys.platform != "darwin",
                    reason="Mach host_statistics64 is darwin-only")
def test_darwin_probe_live_measures_real_memory():
    """Field acceptance on a real Mac: the probe reports a measured value
    (status ok) that is not the 4 GB floor constant."""
    import apk_mem_gate as g
    avail, probe, detail = g._avail_probe()
    assert probe == "ok", detail
    assert avail > 0, avail
    assert avail != g.DEFAULTS["apk_mem_floor_gb"], avail