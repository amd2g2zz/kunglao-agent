# -*- coding: utf-8 -*-
"""tests/test_oracle301_go_fixture.py — #301 fixture compilation probe.

The #301 legal-side fixtures ship a tiny synthetic Go target
(``tests/fixtures/oracle301/sample_arx.go``): SHA-1 family constant
K0=0x5A827999 plus a toy ARX step, and a 14-pair captured set
(``captured_pairs.json``) for the C2 "pair-match >=11 of 14" contract
shape.

This module is INTEGRATION tier (default: unlisted in tests/_tiers.py) —
it shells out to the go toolchain when available; without one the
compile test self-skips, and the source-level + model-level pins in
tests/test_case_admission_301.py still hold (they need no toolchain).

Tier pattern: tests/_tiers.py fast rules; compilation = integration tier.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIX301 = ROOT / "tests" / "fixtures" / "oracle301"


def _go_available() -> bool:
    return shutil.which("go") is not None


def test_go_toolchain_compiles_the_fixture(tmp_path: Path) -> None:
    """`go vet`-grade probe: the synthetic target compiles (integration
    tier; skipped without a go toolchain)."""
    if not _go_available():
        pytest.skip("go toolchain not available on this machine")
    src = FIX301 / "sample_arx.go"
    out = tmp_path / "sample_arx"
    proc = subprocess.run(
        ["go", "build", "-o", str(out), str(src)],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert out.exists()


def test_compiled_fixture_reproduces_the_captured_pairs(
        tmp_path: Path) -> None:
    """When the toolchain exists, the compiled binary must reproduce the
    14 captured pairs byte-exact — the C2 contract's comparator is real
    end to end (source -> binary -> pairs)."""
    if not _go_available():
        pytest.skip("go toolchain not available on this machine")
    proc = subprocess.run(
        ["go", "run", str(FIX301 / "sample_arx.go")],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    got = [json.loads(line) for line in proc.stdout.splitlines()
           if line.strip()]
    golden = json.loads(
        (FIX301 / "captured_pairs.json").read_text(encoding="utf-8"))
    golden = golden["pairs"] if isinstance(golden, dict) else golden
    assert got == golden, "compiled output diverges from the captured set"


def test_pairs_model_consistency_vs_python_arithmetics() -> None:
    """Toolchain-free re-check (runs everywhere): the captured pairs match
    an independent Python model of the declared ARX step."""
    golden = json.loads(
        (FIX301 / "captured_pairs.json").read_text(encoding="utf-8"))
    golden = golden["pairs"] if isinstance(golden, dict) else golden
    k0 = 0x5A827999
    for row in golden:
        x = row["in"]
        y = row["i"] + 1
        rot = (row["i"] % 31) + 1
        rotl = ((y << rot) | (y >> (32 - rot))) & 0xFFFFFFFF
        out = ((x + rotl + 0x9E3779B9) & 0xFFFFFFFF) ^ k0
        assert out == row["out"], f"pair {row['i']} diverges from the model"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))
