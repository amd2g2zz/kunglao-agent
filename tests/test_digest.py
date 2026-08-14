# -*- coding: utf-8 -*-
"""tests/test_digest.py — digest 机械生成 (issue #3, design-spec §3.6).

RED: build_digest 产出六节 markdown, 2-4KB, 数字保真, 完整性。
"""
from __future__ import annotations

from pathlib import Path

import digest_build as db


def _scaffold_ws(tmp_path: Path) -> Path:
    """合成 workspace: task_spec + claim-register + facts/_INDEX + progress + failure-registry."""
    (tmp_path / "task_spec.yaml").write_text(
        "primary_questions:\n  - q1: sample family attribution\n  - q2: C2 config\n"
        "scope: static + dynamic\nconstraints: VM-only execution\ndepth: full teardown\n",
        encoding="utf-8")
    (tmp_path / "claim-register.yaml").write_text(
        "claims:\n"
        "  - {id: C-001, status: PROVEN, statement: sample is Vidar, anchors: [bins/x:0x100]}\n"
        "  - {id: C-002, status: OPEN, statement: C2 = mpd.pegasus-77.biz.id}\n",
        encoding="utf-8")
    (tmp_path / "facts").mkdir()
    (tmp_path / "facts" / "_INDEX.md").write_text(
        "F-001 | PROVEN | C-001 | sample family = Vidar | unit=n/a\n"
        "F-002 | VERIFIED | C-001 | entry RVA = 0x28864 | unit=8-byte ELF slots=811; Ghidra 774\n",
        encoding="utf-8")
    (tmp_path / "progress.txt").write_text(
        "[2026-08-06] C-001 PROVEN; next: C-002 C2 extract\n", encoding="utf-8")
    (tmp_path / "failure-registry.yaml").write_text(
        "rules:\n  - when: VT sandbox says Vidar\n    then: 必须二进制内找硬编码指纹\n    anchor: C-020 eBPF case\n",
        encoding="utf-8")
    return tmp_path


def test_digest_has_six_sections(tmp_path):
    ws = _scaffold_ws(tmp_path)
    md = db.build_digest(ws)
    for marker in ["## head", "## sec_a", "## sec_b", "## sec_c",
                   "## sec_d", "## sec_e", "## sec_f"]:
        assert marker in md, f"digest missing section: {marker}"


def test_digest_size_upper_bound(tmp_path):
    """digest 必须 ≤ 4096 bytes (冷启动上限)。下限 ≥2048 仅对真实 workspace 成立 (E6.1 测)。"""
    ws = _scaffold_ws(tmp_path)
    md = db.build_digest(ws)
    n = len(md.encode("utf-8"))
    assert n <= 4096, f"digest {n} bytes exceeds the 4096 cap"


def test_digest_writes_to_runs(tmp_path):
    ws = _scaffold_ws(tmp_path)
    path = db.write_digest(ws)
    assert path == ws / "runs" / "digest.md"
    assert path.exists()


def test_numeric_fidelity_unit_carried(tmp_path):
    """facts 的 unit 字段原样带入 sec_c (数字口径保真, design-spec §3.6 / numeric-fidelity.md)。"""
    ws = _scaffold_ws(tmp_path)
    md = db.build_digest(ws)
    assert "811" in md and "774" in md


def test_completeness_new_verified_fact_in_digest(tmp_path):
    """新增 verified fact 必须 1 轮内进 digest (完整性, 防 extraction gap)。"""
    ws = _scaffold_ws(tmp_path)
    md_before = db.build_digest(ws)
    assert "F-002" in md_before
    with open(ws / "facts" / "_INDEX.md", "a", encoding="utf-8") as f:
        f.write("F-009 | VERIFIED | C-002 | C2 domain resolved | unit=n/a\n")
    md_after = db.build_digest(ws)
    assert "F-009" in md_after


def test_digest_no_llm_pure_mechanical(tmp_path):
    """build_digest 纯机械 (无 LLM): 除 head 时间戳外两次产出一致。"""
    ws = _scaffold_ws(tmp_path)
    a = db.build_digest(ws)
    b = db.build_digest(ws)
    assert a.split("## sec_a")[1] == b.split("## sec_a")[1]


def test_failure_registry_structured(tmp_path):
    """sec_e 失败规则结构化 (WHEN/THEN/anchor), 非自由文本。"""
    ws = _scaffold_ws(tmp_path)
    md = db.build_digest(ws)
    assert "WHEN" in md
    assert "VT sandbox" in md


def test_digest_handles_empty_workspace(tmp_path):
    """空 workspace 不崩, 产出仍六节。"""
    md = db.build_digest(tmp_path)
    for marker in ["## head", "## sec_a", "## sec_b", "## sec_c",
                   "## sec_d", "## sec_e", "## sec_f"]:
        assert marker in md
