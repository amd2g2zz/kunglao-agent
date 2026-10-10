# -*- coding: utf-8 -*-
"""sign_candidate_verify — differential verification pins (synthetic I/O).

emit: candidates schema validation, locator-kind validation, plan +
harness emission (harness syntax-checked by node when available).
apply: promotion rule (verified iff every sample matched and the match
count clears the minimum), false-with-reason otherwise, and fail-loud on
malformed artifacts.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "web" / "sign_candidate_verify.py"

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node --check needs a node binary")

CANDIDATES = {
    "candidates": [
        {
            "name": "sign",
            "locator": "global:window.__signFn",
            "samples": [
                {"args": ["a", "1"], "expected": "f123"},
                {"args": ["b", "2"], "expected": "g456"},
            ],
        },
        {
            "name": "encrypt",
            "locator": "expr:window.__mod.encrypt",
            "samples": [
                {"args": ["payload"], "expected": "e1"},
            ],
        },
    ]
}


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True, timeout=120)


def _emit(tmp_path: Path, candidates: dict) -> tuple[int, str, str, Path, Path]:
    cfile = tmp_path / "candidates.json"
    cfile.write_text(json.dumps(candidates), encoding="utf-8")
    harness = tmp_path / "harness.js"
    plan = tmp_path / "plan.json"
    r = _run("emit", "--candidates", str(cfile), "--out", str(harness),
             "--plan-out", str(plan))
    return r.returncode, r.stderr, r.stdout, harness, plan


def test_emit_produces_valid_harness_and_plan(tmp_path: Path) -> None:
    rc, err, _, harness, plan = _emit(tmp_path, CANDIDATES)
    assert rc == 0, err
    harness_text = harness.read_text(encoding="utf-8")
    assert "__PLAN__" not in harness_text  # placeholder must be replaced
    assert "window.__signFn" in harness_text
    plan_data = json.loads(plan.read_text(encoding="utf-8"))
    assert plan_data["plan_version"] == 1
    assert len(plan_data["candidates"]) == 2
    check = subprocess.run(["node", "--check", str(harness)],
                           capture_output=True, text=True)
    assert check.returncode == 0, check.stderr


def test_emit_bad_locator_kind_fails_loud(tmp_path: Path) -> None:
    bad = {"candidates": [{"name": "x", "locator": "weird:foo",
                           "samples": [{"args": [], "expected": "e"}]}]}
    rc, err, *_ = _emit(tmp_path, bad)
    assert rc == 2
    assert "locator" in err.lower()


def test_emit_empty_candidates_fails_loud(tmp_path: Path) -> None:
    rc, err, *_ = _emit(tmp_path, {"candidates": []})
    assert rc == 2
    assert err.strip()


def test_emit_bad_sample_fails_loud(tmp_path: Path) -> None:
    bad = {"candidates": [{"name": "x", "locator": "global:window.a",
                           "samples": [{"args": "not-a-list",
                                        "expected": "e"}]}]}
    rc, err, *_ = _emit(tmp_path, bad)
    assert rc == 2
    assert "args" in err.lower()


def test_apply_promotes_all_matched(tmp_path: Path) -> None:
    _, _, _, _, plan = _emit(tmp_path, CANDIDATES)
    plan_data = json.loads(plan.read_text(encoding="utf-8"))
    results = []
    for cand in plan_data["candidates"]:
        for i, _ in enumerate(cand["samples"]):
            results.append({"candidate": cand["name"], "sample_index": i,
                            "ok": True, "got_fingerprint": "x",
                            "expected": "y"})
    results_file = tmp_path / "results.json"
    results_file.write_text(json.dumps({"results": results}),
                            encoding="utf-8")
    cfile = tmp_path / "candidates.json"
    cfile.write_text(json.dumps(CANDIDATES), encoding="utf-8")
    out = tmp_path / "verified.json"
    r = _run("apply", "--results", str(results_file), "--candidates",
             str(cfile), "--out", str(out), "--minimum-matches", "2")
    assert r.returncode == 0, r.stderr
    merged = json.loads(out.read_text(encoding="utf-8"))
    by_name = {c["name"]: c for c in merged["candidates"]}
    assert by_name["sign"]["verified"] is True
    assert by_name["encrypt"]["verified"] is False  # 1 sample < minimum 2
    assert by_name["encrypt"]["verification"][0]["reason"]


def test_apply_partial_mismatch_not_promoted(tmp_path: Path) -> None:
    cfile = tmp_path / "candidates.json"
    cfile.write_text(json.dumps(CANDIDATES), encoding="utf-8")
    results = [
        {"candidate": "sign", "sample_index": 0, "ok": True,
         "got_fingerprint": "f123", "expected": "f123"},
        {"candidate": "sign", "sample_index": 1, "ok": False,
         "got_fingerprint": "zzz", "expected": "g456"},
        {"candidate": "encrypt", "sample_index": 0, "ok": True,
         "got_fingerprint": "e1", "expected": "e1"},
    ]
    results_file = tmp_path / "results.json"
    results_file.write_text(json.dumps({"results": results}),
                            encoding="utf-8")
    out = tmp_path / "verified.json"
    r = _run("apply", "--results", str(results_file), "--candidates",
             str(cfile), "--out", str(out), "--minimum-matches", "1")
    assert r.returncode == 0, r.stderr
    merged = json.loads(out.read_text(encoding="utf-8"))
    by_name = {c["name"]: c for c in merged["candidates"]}
    assert by_name["sign"]["verified"] is False  # one sample mismatched
    reasons = [v.get("reason", "") for v in by_name["sign"]["verification"]]
    assert any(reasons)


def test_apply_missing_result_entry_not_promoted(tmp_path: Path) -> None:
    cfile = tmp_path / "candidates.json"
    cfile.write_text(json.dumps(CANDIDATES), encoding="utf-8")
    # sign sample 1 never ran: absent from results
    results = [{"candidate": "sign", "sample_index": 0, "ok": True,
                "got_fingerprint": "f123", "expected": "f123"}]
    results_file = tmp_path / "results.json"
    results_file.write_text(json.dumps({"results": results}),
                            encoding="utf-8")
    out = tmp_path / "verified.json"
    r = _run("apply", "--results", str(results_file), "--candidates",
             str(cfile), "--out", str(out), "--minimum-matches", "1")
    assert r.returncode == 0, r.stderr
    merged = json.loads(out.read_text(encoding="utf-8"))
    by_name = {c["name"]: c for c in merged["candidates"]}
    assert by_name["sign"]["verified"] is False


def test_apply_malformed_results_fail_loud(tmp_path: Path) -> None:
    cfile = tmp_path / "candidates.json"
    cfile.write_text(json.dumps(CANDIDATES), encoding="utf-8")
    results_file = tmp_path / "results.json"
    results_file.write_text(json.dumps({"results": [
        {"candidate": "sign", "sample_index": 99, "ok": True,
         "got_fingerprint": "x", "expected": "y"},
    ]}), encoding="utf-8")
    out = tmp_path / "verified.json"
    r = _run("apply", "--results", str(results_file), "--candidates",
             str(cfile), "--out", str(out))
    assert r.returncode == 2
    assert r.stderr.strip()


def test_apply_unknown_candidate_fails_loud(tmp_path: Path) -> None:
    cfile = tmp_path / "candidates.json"
    cfile.write_text(json.dumps(CANDIDATES), encoding="utf-8")
    results_file = tmp_path / "results.json"
    results_file.write_text(json.dumps({"results": [
        {"candidate": "ghost", "sample_index": 0, "ok": True,
         "got_fingerprint": "x", "expected": "y"},
    ]}), encoding="utf-8")
    r = _run("apply", "--results", str(results_file), "--candidates",
             str(cfile), "--out", str(tmp_path / "v.json"))
    assert r.returncode == 2
    assert "ghost" in r.stderr


def test_help_carries_examples() -> None:
    r = _run("--help")
    assert r.returncode == 0
    assert "Examples:" in r.stdout
    assert "python tools/web/sign_candidate_verify.py" in r.stdout
