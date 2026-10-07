#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_eval_split_lint_518.py — anti-overfit split registry + leak lint (#518 PR-1).

Owner ruling (2026-10-04): capability mainline = expertise injection, and
evaluation integrity must exist BEFORE injection. The corpus is split into
a mining pool and an interpolation holdout (the six matrix units — fresh
instances of mined families whose three-arm baselines are already
measured); the lint hard-fails any holdout instance constant or unit-id
that reaches the prior/pattern store. A prior that has seen the holdout's
answers is not a prior — it is the answer key.

Pinned here:
  C1  a planted holdout constant in the pattern store bites (both the raw
      string form and the even-hex decimal-int form the checkers accept)
  C2  a planted holdout unit-id bites
  C3  a clean store passes (exit 0)
  C4  the split registry itself is valid (parses, units exist, no overlap,
      every holdout unit carries a ground_truth constants block)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINT = ROOT / "scripts" / "eval_split_lint.py"
SPLIT = ROOT / "eval" / "v1" / "split.yaml"

HOLDOUT_UNITS = (
    "web-token-v1", "web-pow-lite-v1", "apk-static-license-v1",
    "rust-apk-beacon-v1", "web-anticrawl-v2", "apk-webview-attest-v2",
)

# corpus tiers, release first — holdout ground truth resolves across tiers
# (the #546 blocked-path extrapolation units live under toolflex)
_TIERS = ("release", "smoke", "misdirection", "toolflex", "chain")


def _gt_path(unit: str) -> Path:
    for tier in _TIERS:
        p = ROOT / "eval/v1/tasks" / tier / unit / "ground_truth.json"
        if p.is_file():
            return p
    raise FileNotFoundError(f"no ground_truth.json for holdout unit {unit}")


def _gt_constants(unit: str) -> dict:
    return json.loads(_gt_path(unit).read_text(encoding="utf-8")).get(
        "constants") or {}


def _run_lint(store: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(LINT), "--patterns-root", str(store)],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT))


def test_split_registry_exists_and_valid():
    assert SPLIT.is_file(), "eval/v1/split.yaml is the split authority (#518)"
    import yaml  # noqa: PLC0415

    doc = yaml.safe_load(SPLIT.read_text(encoding="utf-8")) or {}
    hold = doc.get("holdout") or {}
    interp = hold.get("interpolation") or []
    extrap = hold.get("extrapolation") or []
    assert sorted(interp) == sorted(HOLDOUT_UNITS), interp
    assert not (set(interp) & set(extrap))
    for u in interp + extrap:
        consts = json.loads(_gt_path(u).read_text(encoding="utf-8")).get(
            "constants")
        assert consts, f"holdout unit {u} has no constants block"


def test_planted_holdout_constant_bites(tmp_path):
    consts = _gt_constants("web-token-v1")
    some = next(iter(consts.values()))
    store = tmp_path / "patterns"
    store.mkdir()
    (store / "family-mod-crypto.md").write_text(
        f"playbook: when hmac-like, try the key {some} early\n",
        encoding="utf-8")
    r = _run_lint(store)
    assert r.returncode != 0, r.stdout + r.stderr
    assert "CONSTANT" in r.stdout, r.stdout


def test_planted_hex_int_form_bites(tmp_path):
    consts = _gt_constants("web-token-v1")
    cand = None
    for v in consts.values():
        s = str(v)
        if len(s) % 2 == 0 and all(c in "0123456789abcdefABCDEF" for c in s):
            cand = s
            break
    assert cand is not None, "web-token-v1 carries an even-hex constant"
    as_int = str(int.from_bytes(bytes.fromhex(cand), "big"))
    store = tmp_path / "patterns"
    store.mkdir()
    (store / "hints.md").write_text(f"magic int form: {as_int}\n",
                                    encoding="utf-8")
    r = _run_lint(store)
    assert r.returncode != 0, r.stdout + r.stderr
    assert "CONSTANT" in r.stdout


def test_planted_unit_id_bites(tmp_path):
    store = tmp_path / "patterns"
    store.mkdir()
    (store / "notes.md").write_text(
        "TODO: also covers the web-anticrawl-v2 shape\n", encoding="utf-8")
    r = _run_lint(store)
    assert r.returncode != 0
    assert "UNIT_ID" in r.stdout


def test_clean_store_passes(tmp_path):
    store = tmp_path / "patterns"
    store.mkdir()
    (store / "family-kdf.md").write_text(
        "# KDF playbook\nstring-array peeling -> IV/K/SBOX mutation checks\n",
        encoding="utf-8")
    r = _run_lint(store)
    assert r.returncode == 0, r.stdout + r.stderr
