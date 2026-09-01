# -*- coding: utf-8 -*-
"""tests/test_user_signal_capture_868.py — #868 捕获/分类/路由核心。

覆盖 issue 验收：全量落账 schema、意愿类生效+可撤销、事实类立案、
分类失败不丢信号（一级兜底）、fail-open 双笼、无信号路径 byte-identical。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import kunglao_log  # noqa: E402
import mission_ledger as ml  # noqa: E402
import user_signal as us  # noqa: E402


def _mk_ws(tmp_path, pqs=("PQ-1", "PQ-2")):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    (ws / "task_spec.yaml").write_text(yaml.safe_dump({
        "primary_questions": [{"id": p, "question": p} for p in pqs],
    }, allow_unicode=True), encoding="utf-8")
    ml.init(ws)
    return ws


def _all_rows(ws):
    rows = []
    for p in sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl")):
        rows.extend(json.loads(line) for line in
                    p.read_text(encoding="utf-8").splitlines() if line.strip())
    return rows


def _load_shim():
    name = "user_signal_capture_868"
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(
            name, ROOT / "hooks" / "user_signal_capture.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


# ---------- classify ----------

def test_prefix_classification():
    assert us.classify("[goal] RCE 才算完成")["ontype"] == "volition"
    assert us.classify("[pref] 少输出中间日志")["route"] == "pref"
    assert us.classify("[fix] 这不是内存问题，是 size gate")["ontype"] == "factual"
    assert us.classify("[constraint] 只用静态分析")["route"] == "constraint"
    assert us.classify("[goal] RCE")["classified_by"] == "prefix"


def test_keyword_fallback_never_loses_signal():
    r = us.classify("这个方向不是内存破坏，应改查 size gate")
    assert r["ontype"] == "factual"
    assert r["classified_by"] == "keyword"
    r2 = us.classify("闲聊一句， nothing relevant here")
    assert r2["classified_by"] == "fallback"
    assert r2["ontype"] == "unrouted"   # 分错不丢信号：仍落账进上下文


# ---------- volition 生效 + 可撤销 ----------

def test_volition_repin_applies_and_revocable(tmp_path):
    ws = _mk_ws(tmp_path)
    sig = us.classify("[goal] add=PQ-3; remove=PQ-2 新目标以 PQ-3 为准")
    r = us.apply_volition(ws, sig)
    assert r["applied"] is True
    led = ml.load(ws)
    ids = [p["id"] for p in led["mission"]["pqs"]]
    assert "PQ-3" in ids and "PQ-2" not in ids
    # 撤销 = 再 re-pin（最后者赢，历史留痕）
    r2 = us.apply_volition(ws, us.classify("[goal] add=PQ-2; remove=PQ-3"))
    ids2 = [p["id"] for p in ml.load(ws)["mission"]["pqs"]]
    assert "PQ-2" in ids2 and "PQ-3" not in ids2
    # value_frame 留痕
    ts = yaml.safe_load((ws / "task_spec.yaml").read_text(encoding="utf-8"))
    assert len(ts["value_frame"]) == 2


def test_volition_unparseable_payload_recorded_only(tmp_path):
    ws = _mk_ws(tmp_path)
    sig = us.classify("[goal] 以最快路径拿到结论")
    r = us.apply_volition(ws, sig)
    assert r["applied"] is False      # 机器不可解析 → 只记录不生效
    led = ml.load(ws)
    assert [p["id"] for p in led["mission"]["pqs"]] == ["PQ-1", "PQ-2"]


# ---------- factual 立案 ----------

def test_factual_files_signal_and_case(tmp_path):
    ws = _mk_ws(tmp_path)
    sig = us.classify("[fix] 这不是内存问题，是 size gate 顺序")
    r = us.file_factual(ws, sig)
    assert r["case_id"]
    case = json.loads((ws / "runs" / "dual-gate" /
                       f"{r['case_id']}.json").read_text(encoding="utf-8"))
    assert case["assertion"]
    assert case["status"] == "open"
    recs = list((ws / "runs" / "user-signals").glob("sig-*.json"))
    assert len(recs) == 1


# ---------- hook shim ----------

def _make_ws_hookable(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    return ws


def test_hook_passes_through_without_workspace(tmp_path, capsys):
    shim = _load_shim()
    rc = shim.process_event({"prompt": "[goal] x", "cwd": str(tmp_path / "nope")})
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_hook_fail_open_on_garbage(tmp_path, capsys):
    shim = _load_shim()
    ws = _make_ws_hookable(tmp_path)
    rc = shim.process_event({"prompt": 12345, "cwd": str(ws)})   # 非字符串 prompt
    assert rc == 0


def test_hook_end_to_end_files_signal(tmp_path, capsys):
    shim = _load_shim()
    ws = _make_ws_hookable(tmp_path)
    ml.init(ws)
    rc = shim.process_event({"prompt": "[fix] 这不是内存问题", "cwd": str(ws)})
    assert rc == 0
    rows = _all_rows(ws)
    assert any(r.get("action") == "user_signal" and r.get("actor") == "user"
               for r in rows)
    assert any(r.get("action") == "user_signal_processed" for r in rows)


# ---------- byte-identical（无信号路径）----------

def test_no_signal_path_is_inert(tmp_path):
    ws = _mk_ws(tmp_path)
    before = (ws / "runs" / "mission_ledger.yaml").read_text(encoding="utf-8")
    assert us.cockpit_face(ws) == {"pending_signals": 0, "recent": []}
    after = (ws / "runs" / "mission_ledger.yaml").read_text(encoding="utf-8")
    assert before == after              # 无信号 → 零写入
    assert _all_rows(ws) == []          # 零事件
