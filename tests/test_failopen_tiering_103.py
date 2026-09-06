# -*- coding: utf-8 -*-
"""tests/test_failopen_tiering_103.py — #103 四实例 TDD（audit A6 拆分）。

fail-open 无分级，导致 "不能死锁" 被实现成 "任何异常 = 通过"。四个实例：
  1. 坏字节过交付门：fact/summary 一个非法 UTF-8 字节 → 判别器 raise
     UnicodeDecodeError → completion_gate 双笼吞成 PASS。修法：判别器
     read_text 统一 errors="replace"（坏字节降级为内容，不降级为通过）。
  2. 证据清零：_dispatched_ids 全吞 except——一行脏 promotion_attempts
     抹掉全部 claim 的 dispatch 证据。修法：per-claim 容错。
  3. DECIDE 整体冻结：promotion_attempts: "two" → int() ValueError 一路
     逃逸到 kunglao-decide 的 conservative BLOCKED。修法：int 转换
     per-claim 守护（不可解析 → 0 + feeds 诊断）。
  4. CJK 跳判：纯中文 note 词集为空 → `if not words: continue` 连 R2/R3
     引用检查一起跳过。修法：仅 R1 依赖词集，R2/R3 照查。

数据全部合成（issue #103 验收表引用），无活体用户数据。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import notes_discriminator as nd  # noqa: E402
import summary_discriminator as sd  # noqa: E402
import rollup  # noqa: E402
from _factories import write_hook_state  # noqa: E402

HOOKS = ROOT / "hooks"


# ---------------------------------------------------------------------------
# 场景 1：坏字节过交付门（判别器 errors="replace"）
# ---------------------------------------------------------------------------

FACT_PROVEN = (
    "---\nid: F001\nstatus: PROVEN\n---\n"
    "handler at 0x14002abcd, allocation 0x150 via size gate.\n")

# 同一 fact 的坏字节形态：0x80 混进正文（PARTIALLY-VERIFIED + 不确定性词）
FACT_PARTIAL_BAD_BYTE = (
    b"---\nid: F002\nstatus: PARTIALLY-VERIFIED\n---\n"
    b"offset 0x150 \x80 unconfirmed pending dynamic check.\n")


def _mk_ws(tmp_path, *, facts_bytes: dict | None = None,
           facts: dict | None = None, summary: str | bytes | None = None):
    facts_dir = tmp_path / "facts"
    facts_dir.mkdir(exist_ok=True)
    for name, body in (facts or {}).items():
        (facts_dir / name).write_text(body, encoding="utf-8")
    for name, body in (facts_bytes or {}).items():
        (facts_dir / name).write_bytes(body)
    if summary is not None:
        p = tmp_path / "summary.md"
        if isinstance(summary, bytes):
            p.write_bytes(summary)
        else:
            p.write_text(summary, encoding="utf-8")
    return tmp_path


def test_bad_byte_fact_summary_discriminator_reports_violation(tmp_path):
    """场景 1：fact 文件含 0x80 → sd.check 返回带 violation 的结果，不 raise。"""
    ws = _mk_ws(tmp_path,
                facts={"F001.md": FACT_PROVEN},
                facts_bytes={"F002.md": FACT_PARTIAL_BAD_BYTE},
                summary="# 分析收敛完成\n\nq1 已全部闭合，协议已完整还原。\n")
    r = sd.check(ws / "summary.md", ws / "facts")
    assert isinstance(r, dict) and "violations" in r
    assert r["ok"] is False
    assert r["violations"], "bad byte must degrade to content, never to pass"


def test_bad_byte_summary_summary_discriminator_reports_violation(tmp_path):
    """场景 1b：summary.md 本身含 0x80（sd:60 的 read_text）→ 不 raise 且完成词仍判。"""
    summary_bytes = ("# 分析收敛完成\n\nfully reverse complete \x80 done\n"
                     ).encode("utf-8", errors="ignore") + b"\x80 rest\n"
    ws = _mk_ws(tmp_path,
                facts={"F001.md": FACT_PROVEN,
                       "F002.md": FACT_PARTIAL_BAD_BYTE.decode(
                           "utf-8", errors="replace")},
                summary=summary_bytes)
    r = sd.check(ws / "summary.md", ws / "facts")
    assert isinstance(r, dict) and "violations" in r
    assert r["ok"] is False
    assert any("completion claim" in v for v in r["violations"]), r


def test_bad_byte_fact_notes_discriminator_reports_violation(tmp_path):
    """场景 1c：notes 判别器的 fact 语料读取（nd:72）同样 errors="replace"。"""
    facts_dir = tmp_path / "facts"
    facts_dir.mkdir()
    (facts_dir / "F001.md").write_bytes(
        b"---\nid: F001\nstatus: PROVEN\n---\n"
        b"handler at 0x14002abcd allocates 0x150 bytes \x80 via gate.\n")
    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()
    (notes_dir / "C-001.md").write_text(
        "---\nid: C-001\nclaim_id: C-001\nverify_status: pending\n---\n"
        "This narrative concludes without citing any evidence id at all: "
        "quixotic velvet thunderstorm.\n", encoding="utf-8")
    r = nd.check(notes_dir, facts_dir)
    assert isinstance(r, dict) and "violations" in r
    assert r["ok"] is False
    assert any("no fact-id reference" in v for v in r["violations"]), r


def _load_gate_shim():
    name = "completion_gate_hook_103"
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(
            name, HOOKS / "completion_gate.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


def _gate_ws(tmp_path):
    """激活态 would-PASS workspace（形状照抄 test_summary_fake_826）。"""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [{"id": "C-302", "status": "PROVEN"}]},
                       allow_unicode=True), encoding="utf-8")
    rollup.sweep_terminal_claims(ws)
    write_hook_state(ws, active_hooks=["completion_gate"],
                     ts="2026-08-13T00:00:00Z", tier="none",
                     phase="IDLE", user_override={},
                     expires_minutes=30)
    (ws / "task-oracle.yaml").write_text(yaml.safe_dump(
        {"task_text": "analyze the payload",
         "open_items": [{"id": "OC-1", "closed_by": "verifier"}]},
        sort_keys=False), encoding="utf-8")
    (ws / "facts").mkdir(exist_ok=True)
    (ws / "facts" / "F001.md").write_text(FACT_PROVEN, encoding="utf-8")
    (ws / "facts" / "F002.md").write_bytes(FACT_PARTIAL_BAD_BYTE)
    (ws / "notes").mkdir(exist_ok=True)
    (ws / "notes" / "C-302.md").write_text(
        "---\nid: C-302\nclaim_id: C-302\nverify_status: pending\n"
        "---\n# durable result\n\n"
        "Timing analysis: the size gate precedes the handler write. "
        "Evidence: F001, F002.\n", encoding="utf-8")
    # summary 会蒸发 F002 的不确定性（完成词 + 无暂定节）——若坏字节被
    # errors=replace 降级为内容，R1/R2 必然可见。
    (ws / "summary.md").write_text(
        "# 分析收敛完成\n\nq1 已全部闭合，协议已完整还原。\n", encoding="utf-8")
    return ws


def test_completion_gate_bad_byte_blocks_not_passes(tmp_path, capsys):
    """场景 1 交付门：坏字节不再经 UnicodeDecodeError 笼子变成 PASS → rc=7。"""
    shim = _load_gate_shim()
    ws = _gate_ws(tmp_path)
    rc = shim.process_event({"cwd": str(ws)})
    out = capsys.readouterr().out
    assert rc != 0, f"bad byte must not dissolve into PASS, got rc=0 out={out}"
    decision = json.loads(out)
    assert decision["decision"] == "block"
    assert "SUMMARY_FAKE" in decision["reason"], decision["reason"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
