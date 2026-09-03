# -*- coding: utf-8 -*-
"""tests/test_mission_ledger_823.py — #823-P1 欠账表 + V_m（shadow）。

核心验收 = 防傻断言：边角料 claims 全 PROVEN、与 PQ 零关联 → V_m 增量严格 =0。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import mission_ledger as ml  # noqa: E402


def _mk_ws(tmp_path, pqs, claims, spec_extra=None):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    spec = {"primary_questions": pqs}
    if spec_extra:
        spec.update(spec_extra)
    (ws / "task_spec.yaml").write_text(
        yaml.safe_dump(spec, allow_unicode=True), encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True), encoding="utf-8")
    return ws


def _claim(cid, status="PROVEN", answers=None):
    c = {"id": cid, "status": status}
    if answers is not None:
        c["answers_question"] = answers
    return c


def test_init_shapes_canonical_legacy_string(tmp_path):
    ws = _mk_ws(tmp_path,
                [{"id": "q1", "question": "RCE reachability", "need": "evidence"},
                 {"q2": "packer family?"},
                 "q3 free text"],
                [])
    led = ml.init(ws, None)
    # 解析合同与 decide 一致：纯字符串条目 = 整串即 id
    ids = [p["id"] for p in led["mission"]["pqs"]]
    assert ids == ["q1", "q2", "q3 free text"]
    assert all(p["state"] == "unattempted" for p in led["mission"]["pqs"])
    assert all(p["coverage"] == 0.0 for p in led["mission"]["pqs"])


def test_init_malformed_raises(tmp_path):
    ws = _mk_ws(tmp_path, [{"id": ""}], [])
    import pytest
    with pytest.raises(ValueError):
        ml.init(ws, None)


def test_init_feature_unused(tmp_path):
    ws = _mk_ws(tmp_path, [], [])
    led = ml.init(ws, None)
    assert led["mission"]["pqs"] == []
    assert led["mission"].get("feature_used") is False


def test_proven_hit_rises(tmp_path):
    ws = _mk_ws(tmp_path, [{"id": "q1"}, {"id": "q2"}],
                [_claim("C-1", answers="q1")])
    ml.init(ws, None)
    ml.update(ws)
    v = ml.value_m(ws)
    assert v["v_m"] == 1.0  # 蓝图公式无归一化：answered w=1 cov=1 → 1.0
    assert v["a_t"] == 1.0  # first checkpoint vs empty history base 0.0


def test_anti_stupid_edge_claims_zero_delta(tmp_path):
    """防傻断言：边角料全 PROVEN、与 PQ 零关联 → V_m 增量严格 0。"""
    ws = _mk_ws(tmp_path, [{"id": "q1"}, {"id": "q2"}],
                [_claim("C-edge-1"), _claim("C-edge-2", status="VERIFIED"),
                 _claim("C-edge-3", answers=None)])
    ml.init(ws, None)
    v0 = ml.value_m(ws)["v_m"]
    ml.update(ws)
    v = ml.value_m(ws)
    assert v["v_m"] == 0.0
    assert v["a_t"] == 0.0
    assert v["v_m"] - v0 == 0.0


def test_blocked_requires_blocker_and_wake(tmp_path):
    ws = _mk_ws(tmp_path, [{"id": "q1"}], [])
    ml.init(ws, None)
    import pytest
    with pytest.raises(ValueError):
        ml.mark_blocked(ws, "q1", blocker="vm unreachable", wake=None)
    with pytest.raises(ValueError):
        ml.mark_blocked(ws, "q1", blocker=None, wake="new tool")
    with pytest.raises(ValueError):
        ml.mark_blocked(ws, "q1", blocker=None, wake=None)


def test_blocked_credit_and_proven_override(tmp_path):
    ws = _mk_ws(tmp_path, [{"id": "q1"}, {"id": "q2"}], [])
    ml.init(ws, None)
    ml.mark_blocked(ws, "q2", blocker="vm unreachable",
                    wake="vm_reachable==true")
    v = ml.value_m(ws)["v_m"]
    assert abs(v - 0.3) < 1e-9  # β·w = 0.3（公式无归一化）
    ml.update(ws)  # no PROVEN hit yet — blocked survives update
    assert ml.value_m(ws)["v_m"] == v
    (Path(ws) / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [_claim("C-9", answers="q2")]},
                       allow_unicode=True), encoding="utf-8")
    ml.update(ws)  # PROVEN overrides blocked
    assert ml.value_m(ws)["v_m"] == 1.0


def test_a_t_history(tmp_path):
    ws = _mk_ws(tmp_path, [{"id": "q1"}], [])
    ml.init(ws, None)
    v1 = ml.value_m(ws)
    assert v1["prev_v_m"] == 0.0 and v1["a_t"] == 0.0
    (Path(ws) / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [_claim("C-1", answers="q1")]},
                       allow_unicode=True), encoding="utf-8")
    ml.update(ws)
    v2 = ml.value_m(ws)
    assert v2["prev_v_m"] == 0.0 and v2["a_t"] == 1.0
    v3 = ml.value_m(ws)
    assert v3["prev_v_m"] == 1.0 and v3["a_t"] == 0.0


def test_emit_snapshot_schema(tmp_path):
    ws = _mk_ws(tmp_path, [{"id": "q1"}],
                [_claim("C-1", answers="q1")])
    ml.init(ws, None)
    ml.update(ws)
    ml.emit_snapshot(ws, epoch=1, arm="N")
    rows = []
    for p in sorted((Path(ws) / "runs" / "logs").glob("kunglao-*.jsonl")):
        rows += [json.loads(line)
                 for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    snap = [r for r in rows if r["action"] == "mission_snapshot"]
    assert len(snap) == 1, rows
    ev = snap[0]
    assert ev["actor"] == "mission_ledger"
    for k in ("arm", "epoch", "version", "hypothesis_ref"):
        assert k in ev, k
    assert ev["arm"] == "N" and ev["epoch"] == 1
    assert ev["version"]  # auto git SHA
    detail = json.loads(ev["detail"])
    assert detail["v_m"] == 1.0 and detail["a_t"] == 1.0
    assert detail["answered"] == 1


def test_update_idempotent(tmp_path):
    ws = _mk_ws(tmp_path, [{"id": "q1"}], [_claim("C-1", answers="q1")])
    ml.init(ws, None)
    ml.update(ws)
    led1 = ml.load(ws)
    ml.update(ws)
    led2 = ml.load(ws)
    assert led1 == led2
