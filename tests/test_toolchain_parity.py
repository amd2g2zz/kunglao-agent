# -*- coding: utf-8 -*-
"""Toolchain-parity pins: a declared decompiler lane ARMS the supply
gate.

Field evidence (matrix4c, asl): the android row already probes the
3-path OR supply (analyzeHeadless | idat64 | MCP ghidra/ida-pro-vm)
when a native lib is present — and correctly recorded FAIL — but
DEGRADED_CHECKS unconditionally waives the row, so toolless analysis
proceeded on native units. The gap is not detection, it is arming.

The fix, contract-level:
  A. task_spec tools.decompiler_lane=required makes ghidra/
     mcp_registered BLOCKING (undeclared stays degraded, unchanged).
  B. the e2e face threads the unit's task.yaml tools declaration into
     the workspace task_spec (the product's own file).
  C. difficulty: a native entry with absent scanner evidence is
     UNKNOWN, never easy (the absence-gap rule's dark side).
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)


def _run_env_check(ws):
    import os
    env = dict(os.environ)
    env.pop("GHIDRA_HOME", None)
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "env_check.py"), str(ws)],
        capture_output=True, text=True, timeout=180, env=env)


def test_declared_lane_arms_the_supply_gate(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "task_spec.yaml").write_text(
        "tools:\n  decompiler_lane: required\n", encoding="utf-8")
    (ws / "bins").mkdir()
    import struct
    _e = bytearray(64); _e[0:4] = b"\x7fELF"; _e[4] = 2; _e[5] = 1; _e[6] = 1
    struct.pack_into("<HHI", _e, 16, 3, 0xB7, 1)
    (ws / "bins" / "libnative.so").write_bytes(bytes(_e) + b"\x00" * 64)
    _run_env_check(ws)
    rep = json.loads((ws / "runs" / ".env-check.json").read_text(
        encoding="utf-8"))
    row = rep["checks"].get("ghidra") or rep["checks"].get("mcp_registered")
    assert row is not None, rep["checks"].keys()
    assert row["status"] == "FAIL"
    assert row["blocking"] is True, row          # armed: no waiver
    assert rep["overall"] == "FAIL"


def test_undeclared_lane_stays_degraded(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "task_spec.yaml").write_text("q: 1\n", encoding="utf-8")
    (ws / "bins").mkdir()
    import struct
    _e = bytearray(64); _e[0:4] = b"\x7fELF"; _e[4] = 2; _e[5] = 1; _e[6] = 1
    struct.pack_into("<HHI", _e, 16, 3, 0xB7, 1)
    (ws / "bins" / "libnative.so").write_bytes(bytes(_e) + b"\x00" * 64)
    _run_env_check(ws)
    rep = json.loads((ws / "runs" / ".env-check.json").read_text(
        encoding="utf-8"))
    row = rep["checks"].get("ghidra")
    assert row is not None and row["status"] == "FAIL"
    assert row["blocking"] is False, row         # unchanged semantics
    assert "degraded" in rep


def test_e2e_threads_tools_into_task_spec(tmp_path):
    """The unit's task.yaml tools declaration lands in the workspace
    task_spec (the product file the gates read)."""
    from e2e import checkpoints as cp
    import yaml
    task = tmp_path / "task.yaml"
    task.write_text(yaml.safe_dump({
        "task_id": "u",
        "tools": {"decompiler_lane": "required", "unpack": "apk"}}),
        encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "task_spec.yaml").write_text("q: 1\n", encoding="utf-8")
    cp._merge_unit_tools(ws, task)
    doc = yaml.safe_load((ws / "task_spec.yaml").read_text(encoding="utf-8"))
    assert doc["tools"]["decompiler_lane"] == "required", doc
    assert doc["tools"]["unpack"] == "apk", doc


def test_native_entry_without_evidence_is_unknown(tmp_path):
    """A native sample with zero scanner output calibrates unknown."""
    import difficulty_calibration as dc
    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("lib/arm64-v8a/libn.so", b"\x7fELF")
    (ws / "bins" / "sample.apk").write_bytes(buf.getvalue())
    # no evidence/ dir at all — absent scanners
    out = dc.calibrate_workspace(ws)
    assert out["tier"] == "unknown", out["tier"]


def test_nonnative_entry_keeps_easy_default(tmp_path):
    import difficulty_calibration as dc
    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    (ws / "bins" / "sdk.js").write_text("var x=1", encoding="utf-8")
    out = dc.calibrate_workspace(ws)
    assert out["tier"] == "easy", out["tier"]
