# -*- coding: utf-8 -*-
"""tests/test_evidence_index.py — evidence index builder (P1 + P3 ICD-203 source reliability).

RED: build_evidence_index 扫 raw 证据(排除派生),eid→path+sha256 可溯。
P3: 每条 entry 带 source_reliability(Admiralty A-F/1-6)。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import build_evidence_index as bei


def _write(p: Path, content: bytes | str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))


def _fixture(ws: Path) -> Path:
    _write(ws / "evidence" / "x64dbg-c206-capture.txt", "capture line1\ncapture line2\n")
    _write(ws / "evidence" / "yara-packer-C003.json", '{"packer": "upx"}')
    _write(ws / "evidence" / "verdict.json", '{"verdict": "malware"}')  # 派生
    _write(ws / "analysis_artifacts" / "vm_runtime" / "full_trace.txt", "TRACE " * 100)
    _write(ws / "analysis_artifacts" / "vm_runtime" / "summary.json", '{"net": 0}')  # 派生
    return ws


def _fixture_rich(ws: Path) -> Path:
    """Fixture with diverse evidence types for reliability testing."""
    _write(ws / "evidence" / "capture-c206.txt", "capture data")
    _write(ws / "evidence" / "trace-syscall.txt", "trace data")
    _write(ws / "evidence" / "memory-dump.bin", b"\x00" * 64)
    _write(ws / "evidence" / "decompile-func.txt", "decompiled code")
    _write(ws / "evidence" / "disasm-main.txt", "disasm output")
    _write(ws / "evidence" / "yara-packer.json", '{"yara": "upx"}')
    _write(ws / "evidence" / "tool-output.json", '{"tool": "die"}')
    _write(ws / "evidence" / "cti-vt.json", '{"vt": "report"}')
    _write(ws / "evidence" / "sandbox-cape.json", '{"cape": "report"}')
    _write(ws / "evidence" / "network.pcap", b"\xd4\xc3\xb2\xa1" * 10)
    return ws


# ── P1 tests (existing) ──────────────────────────────────────────────

def test_scan_registers_raw_excludes_derivation(tmp_path):
    ws = _fixture(tmp_path)
    idx = bei.build_index(ws)
    paths = {e["path"] for e in idx["entries"]}
    assert any("x64dbg-c206-capture" in p for p in paths)
    assert any("full_trace" in p for p in paths)
    assert any("yara-packer" in p for p in paths)
    assert not any("summary.json" in p for p in paths), "derived summary.json must not enter the index"
    assert not any("verdict.json" in p for p in paths), "derived verdict.json must not enter the index"


def test_eid_path_resolves_and_sha256_matches(tmp_path):
    ws = _fixture(tmp_path)
    idx = bei.build_index(ws)
    for e in idx["entries"]:
        p = ws / e["path"]
        assert p.exists(), f"path 不存在: {e['path']}"
        actual = hashlib.sha256(p.read_bytes()).hexdigest()
        assert e["sha256"] == actual, f"hash 不匹配: {e['path']}"


def test_entry_has_required_fields(tmp_path):
    ws = _fixture(tmp_path)
    idx = bei.build_index(ws)
    for e in idx["entries"]:
        for k in ("eid", "path", "sha256", "size", "type"):
            assert k in e, f"missing field {k}: {e}"
    eids = [e["eid"] for e in idx["entries"]]
    assert len(eids) == len(set(eids)), "eid 唯一"


def test_write_index_json_and_md(tmp_path):
    ws = _fixture(tmp_path)
    bei.build_and_write(ws)
    idx_path = ws / "evidence" / "_index.json"
    md_path = ws / "evidence" / "_INDEX.md"
    assert idx_path.exists()
    assert md_path.exists()
    data = json.loads(idx_path.read_text(encoding="utf-8"))
    assert "entries" in data
    md = md_path.read_text(encoding="utf-8")
    for e in data["entries"]:
        assert e["eid"] in md


def test_empty_workspace_no_crash(tmp_path):
    idx = bei.build_index(tmp_path)
    assert idx["entries"] == []


def test_type_classification(tmp_path):
    ws = _fixture(tmp_path)
    idx = bei.build_index(ws)
    by_path = {e["path"]: e["type"] for e in idx["entries"]}
    cap = [p for p in by_path if "capture" in p][0]
    trc = [p for p in by_path if "full_trace" in p][0]
    assert by_path[cap] in ("capture", "text"), f"capture type: {by_path[cap]}"
    assert by_path[trc] in ("trace", "text"), f"trace type: {by_path[trc]}"


# ── P3 ICD-203 source reliability tests ──────────────────────────────

def test_source_reliability_field_exists(tmp_path):
    """Every index entry must have a source_reliability field."""
    ws = _fixture_rich(tmp_path)
    idx = bei.build_index(ws)
    assert len(idx["entries"]) > 0, "fixture should produce entries"
    for e in idx["entries"]:
        assert "source_reliability" in e, f"缺 source_reliability: {e}"
        val = e["source_reliability"]
        assert isinstance(val, str), f"source_reliability 应为 str: {val}"
        assert len(val) == 2, f"source_reliability 应为 2 字符(如 A1): {val}"
        assert val[0] in "ABCDEF", f"source_reliability 首字符应 A-F: {val}"
        assert val[1] in "123456", f"source_reliability 次字符应 1-6: {val}"


def test_mechanical_defaults_by_type(tmp_path):
    """Mechanical default source_reliability assigned by evidence type."""
    ws = _fixture_rich(tmp_path)
    idx = bei.build_index(ws)
    by_type = {}
    for e in idx["entries"]:
        by_type[e["type"]] = e["source_reliability"]

    # Direct observation types -> A1
    assert by_type.get("capture") == "A1", f"capture should be A1, got {by_type.get('capture')}"
    assert by_type.get("trace") == "A1", f"trace should be A1, got {by_type.get('trace')}"
    assert by_type.get("dump") == "A1", f"dump should be A1, got {by_type.get('dump')}"
    assert by_type.get("pcap") == "A1", f"pcap should be A1, got {by_type.get('pcap')}"

    # Tool-derived from artifact -> A2
    assert by_type.get("decompile") == "A2", f"decompile should be A2, got {by_type.get('decompile')}"
    assert by_type.get("disasm") == "A2", f"disasm should be A2, got {by_type.get('disasm')}"

    # Tool pattern match -> B2
    assert by_type.get("yara-scan") == "B2", f"yara-scan should be B2, got {by_type.get('yara-scan')}"

    # CTI third-party -> C5
    assert by_type.get("cti") == "C5", f"cti should be C5, got {by_type.get('cti')}"

    # Sandbox -> D3
    assert by_type.get("sandbox") == "D3", f"sandbox should be D3, got {by_type.get('sandbox')}"


def test_custom_rel_map_overrides_default(tmp_path):
    """--rel reliability_map.yaml overrides mechanical defaults."""
    ws = _fixture_rich(tmp_path)
    rel_map = {
        "by_type": {
            "json": "A1",
            "cti": "B2",
        },
    }
    idx = bei.build_index(ws, rel_map=rel_map)
    by_type = {}
    for e in idx["entries"]:
        by_type.setdefault(e["type"], []).append(e["source_reliability"])

    # json overridden to A1
    if "json" in by_type:
        assert all(r == "A1" for r in by_type["json"]), \
            f"json overridden to A1, got {by_type['json']}"
    # cti overridden to B2
    if "cti" in by_type:
        assert all(r == "B2" for r in by_type["cti"]), \
            f"cti overridden to B2, got {by_type['cti']}"


def test_eid_specific_override_takes_precedence(tmp_path):
    """eid-specific override in rel_map takes precedence over type-specific."""
    ws = _fixture_rich(tmp_path)
    idx_default = bei.build_index(ws)
    target_eid = idx_default["entries"][0]["eid"]
    target_type = idx_default["entries"][0]["type"]

    rel_map = {
        target_eid: "F6",
        "by_type": {
            target_type: "B2",
        },
    }
    idx = bei.build_index(ws, rel_map=rel_map)
    for e in idx["entries"]:
        if e["eid"] == target_eid:
            assert e["source_reliability"] == "F6", \
                f"eid-specific should be F6, got {e['source_reliability']}"


def test_reliability_in_written_json(tmp_path):
    """Written _index.json includes source_reliability in every entry."""
    ws = _fixture_rich(tmp_path)
    bei.build_and_write(ws)
    data = json.loads((ws / "evidence" / "_index.json").read_text("utf-8"))
    for e in data["entries"]:
        assert "source_reliability" in e, f"written entry missing source_reliability: {e}"


def test_reliability_column_in_md(tmp_path):
    """Written _INDEX.md includes source_reliability column."""
    ws = _fixture_rich(tmp_path)
    bei.build_and_write(ws)
    md = (ws / "evidence" / "_INDEX.md").read_text("utf-8")
    assert "source_reliability" in md or "reliability" in md.lower(), \
        "MD should mention source_reliability"
