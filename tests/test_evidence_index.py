"""tests/test_evidence_index.py — evidence index builder (P1, PRD evidence-integrity).

RED: build_evidence_index 扫 raw 证据(排除派生),eid→path+sha256 可溯。
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


def test_scan_registers_raw_excludes_derivation(tmp_path):
    ws = _fixture(tmp_path)
    idx = bei.build_index(ws)
    paths = {e["path"] for e in idx["entries"]}
    assert any("x64dbg-c206-capture" in p for p in paths)
    assert any("full_trace" in p for p in paths)
    assert any("yara-packer" in p for p in paths)
    assert not any("summary.json" in p for p in paths), "派生 summary.json 不应进 index"
    assert not any("verdict.json" in p for p in paths), "派生 verdict.json 不应进 index"


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
            assert k in e, f"缺字段 {k}: {e}"
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
