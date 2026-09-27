#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_hygiene_rc_silent_handlers.py — record-only extension (F).

Same contract as the record-only batch: every previously-silent fail-open
handler keeps its exact return value/shape and gains one rate-limited
stderr WARN naming op + reason.

Covers:
  - scripts/anomaly_detector.py: the runtime-reachable silent handlers
    (baseline doc ingest, fact yaml block, taint seed table, taint
    evidence read) plus the import-time yaml soft-dependency warn via a
    module reload with yaml stubbed out
  - tools/static/dexdc_scanner.py: the three genuinely-silent handlers
    (pyo3 face import, CLI version probe, taint seeds load). The other
    four except sites in the scanner already record structured reasons
    into the payload — they were not silent and are untouched
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import kunglao_log as kl406  # migrated modules' warn IS this canonical function

REPO = Path(__file__).resolve().parents[1]


def _stderr(capsys) -> str:
    return capsys.readouterr().err


# ---------------------------------------------------------------------------
# scripts/anomaly_detector.py
# ---------------------------------------------------------------------------

def test_baseline_doc_ingest_failure_warns(monkeypatch, capsys):
    import anomaly_detector as ad

    def _boom(*a, **k):
        raise OSError("unreadable doc")

    monkeypatch.setattr(ad, "_ingest_re_library_doc", _boom)
    kl406._WARN_LAST.clear()
    corpus = ad._load_baseline()
    assert corpus.term_freq == {} or isinstance(corpus.term_freq, dict)
    assert "baseline_doc_ingest:" in _stderr(capsys)


def test_extract_sample_refs_broken_yaml_warns(capsys):
    import anomaly_detector as ad
    kl406._WARN_LAST.clear()
    # broken fence AND no line-level sample_refs fallback anywhere, so
    # the only escape is the YAMLError branch under test
    refs = ad._extract_sample_refs("prose\n```yaml\nkey: [broken\n```\n")
    assert refs == []  # shape unchanged
    assert "fact_yaml_block" in _stderr(capsys)


def test_taint_seed_map_unreadable_warns(tmp_path, monkeypatch, capsys):
    import anomaly_detector as ad
    monkeypatch.setattr(ad, "TAINT_SEEDS_FILE", tmp_path)  # a directory
    kl406._WARN_LAST.clear()
    assert ad._taint_seed_map() == {}
    err = _stderr(capsys)
    assert "taint_seed_table" in err


def test_observe_taint_missing_evidence_warns(tmp_path, capsys):
    import anomaly_detector as ad
    kl406._WARN_LAST.clear()
    assert ad.observe_taint(tmp_path) == []
    err = _stderr(capsys)
    assert "taint_evidence_read" in err


def test_yaml_soft_dep_warn_on_import_without_yaml(capsys):
    """Module reload with yaml stubbed out: the import-time soft-dependency
    degradation is recorded, yaml stays None, module state restored after."""
    import anomaly_detector as ad
    saved = sys.modules.get("yaml")
    kl406._WARN_LAST.clear()
    sys.modules["yaml"] = None
    try:
        reloaded = importlib.reload(ad)
        assert reloaded.yaml is None
        assert "yaml_soft_dep" in _stderr(capsys)
    finally:
        if saved is not None:
            sys.modules["yaml"] = saved
        else:
            sys.modules.pop("yaml", None)
        importlib.reload(ad)  # restore real yaml binding
    assert ad.yaml is not None


# ---------------------------------------------------------------------------
# tools/static/dexdc_scanner.py
# ---------------------------------------------------------------------------

def _load_dexdc():
    if str(REPO / "tools" / "static") not in sys.path:
        sys.path.insert(0, str(REPO / "tools" / "static"))
    import dexdc_scanner
    return dexdc_scanner


def test_detect_pyo3_import_failure_warns(monkeypatch, capsys):
    dexdc = _load_dexdc()
    monkeypatch.setitem(sys.modules, dexdc.PYO3_MODULE, None)
    dexdc._WARN_LAST.clear()
    face = dexdc.detect()
    assert "pyo3_face_import" in _stderr(capsys)
    # face contract unchanged: CLI fallback or None — never a crash
    assert face["face"] in ("cli", None)


def test_detect_cli_version_probe_failure_warns(tmp_path, monkeypatch, capsys):
    dexdc = _load_dexdc()
    monkeypatch.setitem(sys.modules, dexdc.PYO3_MODULE, None)
    monkeypatch.setattr(dexdc.shutil, "which",
                        lambda _name: str(tmp_path / "dex-decompile"))

    def _boom(*a, **k):
        raise OSError("spawn failed")

    monkeypatch.setattr(dexdc, "_run", _boom)
    dexdc._WARN_LAST.clear()
    face = dexdc.detect()
    err = _stderr(capsys)
    assert "cli_version_probe" in err
    assert "spawn failed" in err
    assert face["face"] == "cli"
    assert face["version"] is None  # frozen shape


def test_load_seeds_broken_yaml_warns(tmp_path, capsys):
    dexdc = _load_dexdc()
    seeds = tmp_path / "seeds.yaml"
    seeds.write_text("seeds: [broken\n", encoding="utf-8")
    dexdc._WARN_LAST.clear()
    out = dexdc._load_seeds(None, seeds)
    assert out == []
    err = _stderr(capsys)
    assert "taint_seeds_load" in err
