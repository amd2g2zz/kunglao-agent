# -*- coding: utf-8 -*-
"""tests/test_redteam_antitemplate_827.py — #827 TDD。

事故形态：265ms 爆发写 8 个同构模板 verify-redteam-*.md（仅替换 claim id，
body 只有 "KEEP status: PROVEN" 记账语），文件存在≠验证发生。

三规则（蓝图 L2，与 #828 hash 锚 / #831 ledger 锚同风格）：
  T1 授权标记 (b)：body 须含 redteam 词 + verdict 词——canonical 生产者词表
  T2 爆发簇 (a)：≥3 文件归一化体相同（id 打码后 sha256 相等）且 mtime 跨度 ≤5s → 整簇排除
  T3 低阈保留：1-2 个同构文件（<3）不触发簇排除（既有语义保留）
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import plan_drift_detector as pdd  # noqa: E402
import write_gate  # noqa: E402


def _mk_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    (ws / "runs").mkdir()
    (ws / "claim-register.yaml").write_text(
        "claims:\n"
        "- id: C-100\n  status: PROVEN\n"
        "- id: C-101\n  status: PROVEN\n"
        "- id: C-102\n  status: PROVEN\n",
        encoding="utf-8")
    return ws


def _template(p: Path, cid: str) -> None:
    """事故同构模板：无 canonical marker，仅 id 可替换。"""
    p.write_text(
        "KEEP status: PROVEN\n"
        f"claim: {cid}\n"
        "notes: routine verification done, keep as is.\n",
        encoding="utf-8")


def _credible(p: Path, cid: str, detail: str = "pre-handler write") -> None:
    """可信 redteam 记录：canonical 词表 + 每 claim 独立分析句。"""
    p.write_text(
        f"RED-TEAM VERDICT: CONFIRMED\n\n"
        f"claim {cid}: independently reproduced — {detail} at 0x14002abcd, "
        f"offset 0x150; adversarial probes agree.\n",
        encoding="utf-8")


def _spread_mtimes(paths) -> None:
    """把 mtime 拉开 >5s（绕过爆发簇窗口，模拟分散的真实验证）。"""
    base = time.time() - 600
    for i, p in enumerate(paths):
        t = base + i * 6
        import os
        os.utime(p, (t, t))


def test_incident_template_burst_excluded(tmp_path):
    """T1：8 个事故模板（无 marker）→ 全部排除 → UNVERIFIED_EVIDENCE 漂移。"""
    ws = _mk_ws(tmp_path)
    runs = ws / "runs"
    paths = []
    for i in range(8):
        p = runs / f"verify-redteam-C10{i}.md"
        _template(p, f"C-10{i}")
        paths.append(p)
    covered = pdd.extract_verified_claim_ids(runs)
    assert covered == set(), covered
    (ws / "global_plan.txt").write_text("plan mentions C-100\n", encoding="utf-8")
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = pdd.check(ws, active_only=True)
    assert rc == 2  # 3 个 PROVEN 全失覆盖 → 3+ 漂移 = HARD_PAUSE（类文档语义）
    assert "UNVERIFIED_EVIDENCE" in buf.getvalue()


def test_single_no_marker_file_excluded(tmp_path):
    """T1 单文件：无 marker → 排除（(b) 独立于爆发簇）。"""
    ws = _mk_ws(tmp_path)
    runs = ws / "runs"
    _template(runs / "verify-redteam-C100.md", "C-100")
    assert pdd.extract_verified_claim_ids(runs) == set()


def test_marker_bearing_identical_burst_excluded(tmp_path):
    """T2：marker 齐全但归一化体全同 ×3+、5s 内 → 整簇排除。"""
    ws = _mk_ws(tmp_path)
    runs = ws / "runs"
    for i in range(4):
        _credible_identical(runs / f"verify-redteam-C10{i}.md")
    assert pdd.extract_verified_claim_ids(runs) == set()


def _credible_identical(p: Path) -> None:
    p.write_text(
        "RED-TEAM VERDICT: CONFIRMED\n\n"
        "claim C-X: independently reproduced — pre-handler write at "
        "0x14002abcd, offset 0x150; adversarial probes agree.\n",
        encoding="utf-8")


def test_two_identical_files_below_threshold_counted(tmp_path):
    """T3：2 个同构 marker 文件（<3）→ 不触发簇排除，计数保留。"""
    ws = _mk_ws(tmp_path)
    runs = ws / "runs"
    _credible_identical(runs / "verify-redteam-C100.md")
    _credible_identical(runs / "verify-redteam-C101.md")
    covered = pdd.extract_verified_claim_ids(runs)
    assert covered == {"C-100", "C-101"}, covered


def test_credible_distinct_files_counted(tmp_path):
    """基线：独立分析的 marker 文件 → 正常计数，无漂移。"""
    ws = _mk_ws(tmp_path)
    runs = ws / "runs"
    _credible(runs / "verify-redteam-C100.md", "C-100", "size gate A")
    _credible(runs / "verify-redteam-C101.md", "C-101", "size gate B")
    _credible(runs / "verify-redteam-C102.md", "C-102", "size gate C")
    _spread_mtimes([runs / f"verify-redteam-C10{i}.md" for i in range(3)])
    covered = pdd.extract_verified_claim_ids(runs)
    assert covered == {"C-100", "C-101", "C-102"}, covered
    (ws / "global_plan.txt").write_text("plan C-100 C-101 C-102\n", encoding="utf-8")
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = pdd.check(ws, active_only=True)
    assert rc == 0, buf.getvalue()


def test_credible_burst_spread_mtime_counted(tmp_path):
    """同构但 mtime 拉开 >5s → 不算爆发（窗口语义）。"""
    ws = _mk_ws(tmp_path)
    runs = ws / "runs"
    paths = []
    for i in range(3):
        p = runs / f"verify-redteam-C10{i}.md"
        _credible_identical(p)
        paths.append(p)
    _spread_mtimes(paths)
    covered = pdd.extract_verified_claim_ids(runs)
    assert covered == {"C-100", "C-101", "C-102"}, covered


# ---------------- write_gate R1 md 接受面 ----------------

def test_write_gate_template_cluster_rejected(tmp_path):
    """write_gate R1：redteam md 为模板簇 → 不作验证记录。"""
    ws = _mk_ws(tmp_path)
    runs = ws / "runs"
    for i in range(4):
        p = runs / f"verify-redteam-C10{i}.md"
        _credible_identical(p)  # marker 齐全也按簇排除
    (ws / "facts").mkdir()
    (ws / "facts" / "F001.md").write_text(
        "---\nid: F001\nstatus: PROVEN\n---\nbody cites F001 evidence\n",
        encoding="utf-8")
    ok, reason = write_gate._fact_runs_records("F001", ws)
    assert ok is False, reason


def test_write_gate_credible_record_accepted(tmp_path):
    """write_gate R1：可信 redteam 记录（引用 fid + verdict）→ 接受。"""
    ws = _mk_ws(tmp_path)
    runs = ws / "runs"
    (runs / "verify-redteam-C100.md").write_text(
        "RED-TEAM VERDICT: CONFIRMED\nredteam analysis of fact F001: "
        "the F001 offset claim reproduces; adversarial probes agree.\n",
        encoding="utf-8")
    (ws / "facts").mkdir()
    (ws / "facts" / "F001.md").write_text(
        "---\nid: F001\nstatus: PROVEN\n---\nbody cites F001 evidence\n",
        encoding="utf-8")
    ok, reason = write_gate._fact_runs_records("F001", ws)
    assert ok is True, reason
