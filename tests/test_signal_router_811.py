# -*- coding: utf-8 -*-
"""tests/test_signal_router_811.py — #811 意图路由器（信号面）。

覆盖 issue #811 验收 1/3：真实路由（继续/开新方向/暂停/澄清 + 状态查询/
连通性）、生产误路由回归钉（"我不是要续跑，是要开一个新的研究方向" →
开新方向，绝不被 #868 的 "fix"/"不是" 关键字劫走）、unrouted 率遥测 +
钉死阈值、ingest 集成、commit 动作空间对齐（新方向 = switch = 新 episode）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import mission_ledger as ml  # noqa: E402
import signal_router as sr  # noqa: E402
import user_signal as us  # noqa: E402


def _mk_ws(tmp_path):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    (ws / "task_spec.yaml").write_text(yaml.safe_dump({
        "primary_questions": [{"id": "PQ-1", "question": "PQ-1"}],
    }, allow_unicode=True), encoding="utf-8")
    ml.init(ws)
    return ws


# ---------- 生产误路由回归钉 ----------

PROD_MISROUTE = "我不是要续跑，是要开一个新的研究方向"


def test_production_misroute_pin_routes_new_direction():
    """生产钉：该形态必须路由到「开新方向」（switch = 新 episode），
    不再被 keyword "fix"/"不是" 劫走，也不再 fallback。"""
    r = sr.classify_intent(PROD_MISROUTE)
    assert r["intent"] == "new_direction"
    assert r["action"] == "new_direction"
    assert r["commit_action"] == "switch"
    assert r["new_episode"] is True
    assert r["classified_by"] != "fallback"
    # 不落事实域（#868 的误路由形态：立案双门 = 用户被迫重述）
    assert r["route_target"] != "dual_gate"


def test_production_misroute_not_continuation():
    """负向钉：尽管字面含「续跑」，意图是反续跑——绝不能路由 continuation。"""
    r = sr.classify_intent(PROD_MISROUTE)
    assert r["intent"] != "continuation"
    assert r["commit_action"] != "persist"


# ---------- 六类意图各自路由 ----------

def test_intent_classes_route():
    cases = [
        ("继续跑，把 PQ-1 收尾", "continuation"),
        ("开一个新的研究方向，从 ATP 合成酶下手", "new_direction"),
        ("先暂停一下", "pause"),
        ("你没说清楚，澄清一下目标", "clarify"),
        ("现在是什么情况", "status_query"),
        ("VM 网络不通，连不上靶机", "connectivity"),
    ]
    for text, intent in cases:
        r = sr.classify_intent(text)
        assert r["intent"] == intent, f"{text!r}: want {intent}, got {r}"


def test_negation_pivot_post_clause_wins():
    """不是要X，是要Y → 用后半句分类（X 先出现也不劫走）。"""
    r = sr.classify_intent("不是要继续这个方向，是要开新的方向查协议层")
    assert r["intent"] == "new_direction"
    assert r["classified_by"] == "pivot"


def test_fallback_stays_unrouted():
    """真无关闲聊：intent=None（fallback），路由器不硬猜。"""
    r = sr.classify_intent("今天天气不错")
    assert r["intent"] is None
    assert r["classified_by"] == "fallback"
    assert r["commit_action"] is None


# ---------- commit 动作空间对齐（统一模型） ----------

def test_commit_alignment():
    """继续 = persist（同 episode）；开新方向 = switch（新 episode）；
    暂停/澄清 = 非提交算子（commit_action=None，operator 面）。"""
    cont = sr.classify_intent("继续")
    assert cont["commit_action"] == "persist"
    assert cont["new_episode"] is False
    new_dir = sr.classify_intent("开个新方向")
    assert new_dir["commit_action"] == "switch"
    assert new_dir["new_episode"] is True
    for text in ("暂停", "澄清一下"):
        r = sr.classify_intent(text)
        assert r["commit_action"] is None


def test_status_query_targets_narration():
    r = sr.classify_intent("现在是什么情况")
    assert r["route_target"] == "narration"
    howto = sr.classify_intent("通过什么命令进入下一步")
    assert howto["intent"] == "status_query"
    assert howto["route_target"] == "narration"


# ---------- unrouted 率遥测 + 钉死阈值 ----------

def test_route_health_threshold_pinned():
    assert 0.0 < sr.MAX_UNROUTED_RATE < 1.0  # 阈值是钉死的策略常数


def test_route_health_telemetry_after_routing(tmp_path):
    """46 行生产形态夹具（45 unrouted + 1 误路由）逐条过 ingest 后，
    unrouted 率必须落到钉死阈值以下（遥测形状诚实带 total）。"""
    ws = _mk_ws(tmp_path)
    # 生产形态夹具：issue #811 记录的真实用户话语族（座舱三问 + 方向/
    # 续跑/暂停/澄清/连通性）+ 1 条 #868 可路由事实 + 少量真闲聊
    utterances = [
        "我不是要续跑，是要开一个新的研究方向",
        "现在是什么情况", "简单介绍一下分析结果",
        "通过什么命令进入下一步", "怎么开claim", "现在进展如何",
        "继续跑", "先暂停一下", "你没说清楚，澄清一下目标",
        "VM 网络不通，连不上靶机", "开个新方向查协议层",
        "这个方向不是内存破坏，应改查 size gate",
    ] * 3 + ["随口一问 a", "随口一问 b"]
    for text in utterances:
        us.ingest(ws, text)
    health = sr.route_health(ws)
    assert health["total"] == 38
    assert health["rate"] <= sr.MAX_UNROUTED_RATE
    assert health["ok"] is True
    assert set(health) >= {"total", "routed", "unrouted", "rate",
                           "threshold", "ok"}


def test_route_health_all_unrouted_red(tmp_path):
    """全 unrouted 的夹具 → ok=False（遥测见红即知路由器失守）。"""
    ws = _mk_ws(tmp_path)
    for i in range(10):
        us.ingest(ws, f"随口一问 {i}")
    health = sr.route_health(ws)
    assert health["total"] == 10
    assert health["rate"] == 1.0
    assert health["ok"] is False


# ---------- ingest 集成（元/未路由类进路由器） ----------

def test_ingest_routes_unrouted_not_factual(tmp_path):
    """生产误路由行过 ingest：记录带意图字段 + signal_routed 落账；
    本体层保持 unrouted（绝不立案双门）。"""
    ws = _mk_ws(tmp_path)
    out = us.ingest(ws, PROD_MISROUTE)
    assert out["intent"] == "new_direction"
    assert out["routed"] is True
    rec = json.loads((ws / "runs" / "user-signals" /
                      f"{out['signal_id']}.json").read_text(encoding="utf-8"))
    assert rec["ontype"] == "unrouted"
    assert rec["intent"] == "new_direction"
    assert rec["commit_action"] == "switch"
    assert rec["new_episode"] is True
    rows = _log_rows(ws)
    assert any(r.get("action") == "signal_routed" for r in rows)
    # 反向：双门无立案（#868 形态会 open_case）
    assert not (ws / "runs" / "dual-gate").exists()


def test_ingest_status_query_returns_narration_target(tmp_path):
    ws = _mk_ws(tmp_path)
    out = us.ingest(ws, "简单介绍一下分析结果")
    assert out["intent"] == "status_query"
    assert out["route_target"] == "narration"
    assert out["routed"] is True


def test_ingest_fallback_keeps_old_shape(tmp_path):
    """无意图信号：routed=False + 旧形状不破（#868 一级兜底语义保留）。"""
    ws = _mk_ws(tmp_path)
    out = us.ingest(ws, "今天天气不错")
    assert out["routed"] is False
    assert out["intent"] is None


def _log_rows(ws):
    rows = []
    for p in sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl")):
        rows.extend(json.loads(line) for line in
                    p.read_text(encoding="utf-8").splitlines() if line.strip())
    return rows


# ---------- deferral 精度钉（不丢 #868 真事实纠正） ----------

def test_no_intent_pivot_stays_factual(tmp_path):
    """无意图的否定转折（真事实纠正）保持 #868 factual 立案——
    deferral 只在有意图时发生。"""
    ws = _mk_ws(tmp_path)
    out = us.ingest(ws, "这个方向不是内存破坏，应改查 size gate")
    assert out["ontype"] == "factual"


def test_prefix_fix_survives_pivot(tmp_path):
    """[fix] 前缀显式分类永不被 deferral 改道。"""
    ws = _mk_ws(tmp_path)
    out = us.ingest(ws, "[fix] 这不是内存问题，是 size gate 问题")
    assert out["ontype"] == "factual"


def test_ingest_status_query_carries_narration_view(tmp_path):
    """接线钉：状态查询信号直达叙事面——ingest 返回值携带四要素视图
    （生产用户问「现在是什么情况」时不需要第二次调用）。"""
    ws = _mk_ws(tmp_path)
    out = us.ingest(ws, "现在是什么情况")
    assert out["view"] is not None
    assert out["view"]["schema"] == "status-narration/1"
    assert set(out["view"]["faces"]) == {"current", "blockers", "next",
                                         "waiting_on"}


def test_ingest_non_status_query_has_no_view(tmp_path):
    ws = _mk_ws(tmp_path)
    out = us.ingest(ws, PROD_MISROUTE)
    assert "view" not in out
