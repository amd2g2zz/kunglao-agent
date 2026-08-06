"""阶段 5 契约测试: M3 VERIFY / M4 RECORD / M5 MONITOR.

Step 1 RED — 当前状态: kunglao-verify.py / kunglao-record.py / kunglao-monitor.py 不存在 → import 即 RED。

GREEN 目标(阶段 5 判据, E5.1-E5.3):
- E5.1 Expand: verify/record 旁路, 旧 CLI 照旧 diff 空
- E5.2 Migrate: reconciler N=3 轮 checksum 零漂移
- E5.3 Contract: 旧通道只读

核心行为:
- L1 机械层: parse_reproduce → run(只读白名单) → sha256 比对 expected → PASS/FAIL
- L2 对抗层: 派发 kunglao-redteam(独立 subagent, BLIND), 输出 CONFIRMED|REFUTED|UNVERIFIED-WITH-GAP
- anchor_check: PASS 必须带 anchors, 无锚不提升
- ledger 幂等: 同 event_id 两次 record → 1 条
- claims 迁移: 非 orchestrator 写 terminal 状态 → 拒(maker-checker)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


# ---------- L1 机械层判别力 ----------

def _write_fact(ws: Path, fid: str, claim: str, reproduce: str, expected: str) -> Path:
    f = ws / "facts" / f"{fid}.md"
    f.write_text(
        f"---\nid: {fid}\nclaim: {claim}\nreproduce: {reproduce}\nexpected: {expected}\n---\n",
        encoding="utf-8")
    return f


def test_known_fact_pass_fake_fact_fail(ws_factory, contract_validator) -> None:
    """E5 判别力: 已知 PROVEN fact → PASS; 篡改 expected 的假 fact → FAIL."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    facts = ws / "facts"
    facts.mkdir()

    # 真 fact: reproduce 输出与 expected 一致
    _write_fact(ws, "F-001", "Decode PE magic", "import struct; print(hex(0x5A4D))", "0x5a4d")
    # 假 fact: expected 被篡改(与 reproduce 实际输出不符)
    _write_fact(ws, "F-002", "Decode PE magic", "import struct; print(hex(0x5A4D))", "0xdeadbeef")

    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "kunglao-verify.py"), str(ws), "F-001", "--json"],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"kunglao-verify F-001 failed: {r.stderr}"
    out = json.loads(r.stdout)
    contract_validator("verify-output", out)
    assert out["l1"]["verdict"] == "PASS", f"known fact should PASS: {out}"

    r2 = subprocess.run(
        [sys.executable, str(SCRIPTS / "kunglao-verify.py"), str(ws), "F-002", "--json"],
        capture_output=True, text=True, timeout=60)
    out2 = json.loads(r2.stdout)
    assert out2["l1"]["verdict"] == "FAIL", f"fake fact should FAIL: {out2}"


def test_anchor_check_blocks_no_anchor(ws_factory) -> None:
    """无锚 PASS 拒提升: anchor_check(verdict) 无 anchors → False."""
    from kunglao_verify import anchor_check
    v = {"l1": {"verdict": "PASS"}, "anchors": []}
    assert anchor_check(v) is False, "no-anchor PASS must be blocked"


# ---------- M4 ledger 幂等 ----------

def test_ledger_idempotent_same_event_once(ws_factory) -> None:
    """同 event_id 两次 record → 1 条."""
    ws = ws_factory()
    from kunglao_record import record_event, read_events
    ev = {"source_module": "test", "event_type": "fact_written",
          "payload": {"fact_id": "F-001", "claim_id": "C-1"}}
    seq1 = record_event(ws, ev)
    seq2 = record_event(ws, ev)
    assert seq1 == seq2, f"idempotent record should return same seq: {seq1} vs {seq2}"
    events = read_events(ws, "fact_written")
    assert len(events) == 1, f"duplicate event recorded: {len(events)}"


# ---------- M5 monitor TickOutput schema ----------

def test_monitor_tick_output_schema(ws_factory, contract_validator) -> None:
    """TickOutput 校验: heartbeat/active_workers/health/next 字段."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "kunglao-monitor.py"), str(ws), "--json"],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"kunglao-monitor failed: {r.stderr}"
    out = json.loads(r.stdout)
    contract_validator("tick-output", out)


# ---------- M4 claim 迁移 maker-checker ----------

def test_claim_migrator_blocks_worker_terminal(ws_factory) -> None:
    """非 orchestrator 写 terminal 状态 → 拒."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    from kunglao_record import claim_migrator
    ok, reason = claim_migrator(ws, "C-1", "PROVEN", actor="worker-w1")
    assert not ok, f"worker terminal write must be rejected: {reason}"
