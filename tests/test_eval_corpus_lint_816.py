#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_eval_corpus_lint_816.py — the #816 measurement-integrity faces.

Owner ruling (2026-10-24): an RE (逆向) mission must NEVER be solvable by
reading the target's source — handing the agent the ground truth is
self-cheating regardless of how the corpus builder justified it (#551's
source+build-note delivery is OVERRULED). The corpus lint
(scripts/eval_corpus_lint.py) makes a source-shipping black-box unit a
MECHANICAL failure, and the task schema gains the material_class field.

Pinned here:
  F1  THE fail-red fixture: a black-box unit whose target/ carries a
      target-semantics source file → lint red, row names the file
  F2  a clean black-box unit (binary target only) → green
  F3  a source-readable unit shipping source → green (by design)
  F4  undeclared material_class → red (unlintable = invalid)
  F5  declared class contradicting the family registry → red
  F6  unregistered family → red (fail-closed)
  F7  the sweep set: .go/.rs/.py caught, .bin/.so/.txt ignored
  S1  schemas/eval-task-v1.json carries the material_class enum (#816)
  S2  validate_task enforces the material_class enum (executable mirror)
  L1  the live corpus (when present locally) lints clean — the tf-novelvm
      / tf-novelcipher rebuilds stay black-box (skipif: corpus is
      operator-local, never tracked)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
LINT = ROOT / "scripts" / "eval_corpus_lint.py"
SCHEMA = ROOT / "schemas" / "eval-task-v1.json"


def _run_lint(*roots: Path) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(LINT)]
    for r in roots:
        argv += ["--corpus-root", str(r)]
    return subprocess.run(argv, capture_output=True, text=True, timeout=60)


def _write_unit(corpus: Path, unit: str, family: str, tier: str = "release",
                material_class: str | None = "black-box",
                target_files: dict[str, bytes] | None = None) -> Path:
    d = corpus / unit
    d.mkdir(parents=True)
    task: dict = {
        "schema": "kunglao-eval-task/1",
        "task_id": unit,
        "eval_version": "eval-v1.1",
        "tier": tier,
        "source": "constructed",
        "family": family,
        "seed": 1,
        "anchors": {"goal_verbatim": "g", "success_criterion": "s",
                    "verification_method": "reproduction"},
        "workspace_scaffold": {"language": "python", "files": ["a.bin"],
                               "entry": "a.bin", "candidate_contract": "c"},
        "checker": {"kind": "pair-match", "oracles": ["pair-match"],
                    "entrypoint": "checker.py",
                    "metrics": ["ttc_seconds", "dispatch_count",
                                "pass_at_k_contribution", "converged"],
                    "thresholds": {"min_pair_ratio": 0.5}},
        "ground_truth": {"file": "ground_truth.json", "space_bits": 8},
        "contamination": {"held_out": True, "distiller_excluded": True,
                          "provenance": "constructed"},
    }
    if material_class is not None:
        task["material_class"] = material_class
    (d / "task.yaml").write_text(
        yaml.dump(task, sort_keys=False, allow_unicode=True), encoding="utf-8")
    tgt = d / "target"
    tgt.mkdir()
    for name, blob in (target_files or {"payload.bin": b"\x00\x01"}).items():
        p = tgt / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(blob)
    return d


# ---------------------------------------------------------------------------
# F1 — the fail-red face (acceptance: "lint live and red on a fixture that
# ships target source")
# ---------------------------------------------------------------------------

def test_black_box_with_target_source_is_red(tmp_path):
    corpus = tmp_path / "tasks"
    _write_unit(corpus, "tf-leaky-v1", "tf-novelvm", material_class="black-box",
                target_files={"src/vm.rs": b"fn main() {}\n"})
    r = _run_lint(corpus)
    assert r.returncode != 0, r.stdout
    assert "CONTAMINATED[TARGET_SOURCE]" in r.stdout
    assert "target/src/vm.rs" in r.stdout


# ---------------------------------------------------------------------------

def test_black_box_clean_is_green(tmp_path):
    corpus = tmp_path / "tasks"
    _write_unit(corpus, "tf-clean-v1", "tf-novelvm",
                target_files={"payload.bin": b"\x00\x01"})
    r = _run_lint(corpus)
    assert r.returncode == 0, r.stdout
    assert "1 black-box" in r.stdout


def test_source_readable_with_source_is_green(tmp_path):
    corpus = tmp_path / "tasks"
    _write_unit(corpus, "smoke-src-v1", "go-arx", material_class="source-readable",
                target_files={"sample_kdf.go": b"package main\n"})
    r = _run_lint(corpus)
    assert r.returncode == 0, r.stdout


def test_undeclared_material_class_is_red(tmp_path):
    corpus = tmp_path / "tasks"
    _write_unit(corpus, "u-undeclared-v1", "smc-x86", material_class=None)
    r = _run_lint(corpus)
    assert r.returncode != 0, r.stdout
    assert "CONTAMINATED[UNDECLARED]" in r.stdout


def test_registry_mismatch_is_red(tmp_path):
    corpus = tmp_path / "tasks"
    _write_unit(corpus, "u-mismatch-v1", "tf-novelvm",
                material_class="source-readable",
                target_files={"vm": b"\xcf\xfa\xed\xfe"})
    r = _run_lint(corpus)
    assert r.returncode != 0, r.stdout
    assert "CONTAMINATED[REGISTRY_MISMATCH]" in r.stdout


def test_unregistered_family_is_red(tmp_path):
    corpus = tmp_path / "tasks"
    _write_unit(corpus, "u-nofam-v1", "brand-new-family")
    r = _run_lint(corpus)
    assert r.returncode != 0, r.stdout
    assert "CONTAMINATED[UNREGISTERED_FAMILY]" in r.stdout


def test_sweep_extension_set(tmp_path):
    corpus = tmp_path / "tasks"
    _write_unit(corpus, "u-sweep-v1", "tf-novelcipher",
                target_files={"src/cipher.c": b"int main(){}\n",
                              "core.go": b"package main\n",
                              "blob.bin": b"\x00",
                              "img.so": b"\xcf\xfa",
                              "notes.txt": b"hello"})
    r = _run_lint(corpus)
    assert r.returncode != 0, r.stdout
    assert "target/src/cipher.c" in r.stdout
    assert "target/core.go" in r.stdout
    assert ".bin" not in r.stdout.split("TARGET_SOURCE")[1].split("]")[0]
    assert "notes.txt" not in r.stdout


# ---------------------------------------------------------------------------
# S1/S2 — the schema + validator faces
# ---------------------------------------------------------------------------

def test_schema_carries_material_class_enum():
    assert SCHEMA.is_file()
    d = json.loads(SCHEMA.read_text(encoding="utf-8"))
    mc = d["properties"]["material_class"]
    assert mc["enum"] == ["source-readable", "black-box"]
    assert "#816" in mc["description"]


def test_validate_task_enforces_material_class_enum():
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        from eval_dataset import validate_task  # noqa: PLC0415
    finally:
        sys.path.pop(0)
    base = {"schema": "kunglao-eval-task/1", "task_id": "x-v1",
            "eval_version": "eval-v1.1", "tier": "release",
            "source": "constructed", "family": "tf-novelvm", "seed": 1,
            "anchors": {"goal_verbatim": "g", "success_criterion": "s",
                        "verification_method": "reproduction"},
            "workspace_scaffold": {"language": "python", "files": ["a"],
                                   "entry": "a", "candidate_contract": "c"},
            "checker": {"kind": "pair-match", "oracles": ["pair-match"],
                        "entrypoint": "checker.py",
                        "metrics": ["ttc_seconds", "dispatch_count",
                                    "pass_at_k_contribution", "converged"],
                        "thresholds": {"min_pair_ratio": 0.5}},
            "ground_truth": {"file": "ground_truth.json", "space_bits": 8},
            "contamination": {"held_out": True, "distiller_excluded": True,
                              "provenance": "constructed"}}
    ok, _ = validate_task({**base, "material_class": "black-box"})
    assert ok, "black-box accepted"
    ok2, errs = validate_task({**base, "material_class": "binary"})
    assert not ok2 and any("material_class" in e for e in errs)


# ---------------------------------------------------------------------------
# L1 — the live corpus (operator-local; skip when absent)
# ---------------------------------------------------------------------------

_BP_LOCAL = (ROOT.parent.parent / "experiments" / "blocked-path-units")


@pytest.mark.skipif(
    not (ROOT / "eval" / "v1" / "tasks").is_dir() and not _BP_LOCAL.is_dir(),
    reason="the eval corpus is local-only material (never tracked)")
def test_live_corpus_lints_clean():
    roots = []
    tasks = ROOT / "eval" / "v1" / "tasks"
    if tasks.is_dir():
        roots.append(tasks)
    bp = ROOT.parent.parent / "experiments" / "blocked-path-units"
    if bp.is_dir():
        roots.append(bp)
    assert roots, "no live corpus found"
    r = _run_lint(*roots)
    assert r.returncode == 0, r.stdout
