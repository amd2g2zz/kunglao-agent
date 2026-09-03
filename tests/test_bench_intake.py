# -*- coding: utf-8 -*-
"""B1 (#823): bench_intake — manifest validation, fail-closed.

Every violation exits nonzero with a structured report. The intake gate
is the FIRST line of experiment hygiene: bad manifests must never reach
the runner.
"""
import hashlib
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bench_intake


def _sample(tmp: Path, content: bytes = b"PE\x00\x00synthetic") -> tuple[Path, str]:
    p = tmp / "sample.bin"
    p.write_bytes(content)
    return p, hashlib.sha256(content).hexdigest()


def _entry(tmp: Path, **over) -> dict:
    p, sha = _sample(tmp)
    e = {"id": "s1", "stratum": "S1", "path": str(p), "sha256": sha,
         "first_seen": "2026-07", "truth_tier": "A",
         "truth_sources": ["vendor-report-1", "vendor-report-2"],
         "scoring_pqs": ["PQ1"], "excluded_pqs": []}
    e.update(over)
    return e


def _manifest(entries: list[dict]) -> dict:
    return {"schema": "kunglao-bench-manifest/1", "seed": 42,
            "samples": entries}


def _write(tmp: Path, entries: list[dict]) -> Path:
    m = tmp / "manifest.yaml"
    m.write_text(yaml.safe_dump(_manifest(entries), allow_unicode=True),
                 encoding="utf-8")
    return m


def test_valid_manifest_passes(tmp_path):
    report = bench_intake.check(_write(tmp_path, [_entry(tmp_path)]))
    assert report["ok"] is True
    assert report["violations"] == []


def test_sha256_mismatch_rejected(tmp_path):
    entry = _entry(tmp_path)
    entry["sha256"] = "0" * 64
    report = bench_intake.check(_write(tmp_path, [entry]))
    assert report["ok"] is False
    assert any("sha256" in v for v in report["violations"])


def test_stale_first_seen_rejected(tmp_path):
    report = bench_intake.check(
        _write(tmp_path, [_entry(tmp_path, first_seen="2025-01")]))
    assert report["ok"] is False
    assert any("first_seen" in v for v in report["violations"])


def test_single_source_non_aplus_rejected(tmp_path):
    report = bench_intake.check(_write(tmp_path, [
        _entry(tmp_path, truth_sources=["only-one-blog"], truth_tier="B")]))
    assert report["ok"] is False
    assert any("truth_sources" in v for v in report["violations"])


def test_aplus_single_source_accepted(tmp_path):
    report = bench_intake.check(_write(tmp_path, [
        _entry(tmp_path, truth_sources=["theZoo-source"], truth_tier="A+")]))
    assert report["ok"] is True


def test_bad_stratum_rejected(tmp_path):
    report = bench_intake.check(_write(tmp_path, [
        _entry(tmp_path, stratum="S9")]))
    assert report["ok"] is False
    assert any("stratum" in v for v in report["violations"])


def test_sample_inside_repo_rejected(tmp_path, monkeypatch):
    entry = _entry(tmp_path)
    monkeypatch.setattr(bench_intake, "REPO_ROOT",
                        tmp_path / "repo")
    entry["path"] = str(tmp_path / "repo" / "kunglao-bench" / "evil.bin")
    report = bench_intake.check(_write(tmp_path, [entry]))
    assert report["ok"] is False
    assert any("repo" in v for v in report["violations"])


def test_layer_counts_enforced(tmp_path):
    entries = [_entry(tmp_path, id=f"s{i}", stratum="S2") for i in range(3)]
    report = bench_intake.check(_write(tmp_path, entries),
                                expect_counts={"S1": 0, "S2": 3})
    assert report["ok"] is True
    report = bench_intake.check(_write(tmp_path, entries),
                                expect_counts={"S1": 8, "S2": 8})
    assert report["ok"] is False
    assert any("count" in v for v in report["violations"])


def test_missing_sample_file_rejected(tmp_path):
    entry = _entry(tmp_path)
    entry["path"] = str(tmp_path / "ghost.bin")
    report = bench_intake.check(_write(tmp_path, [entry]))
    assert report["ok"] is False
    assert any("missing" in v for v in report["violations"])
