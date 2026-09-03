# -*- coding: utf-8 -*-
"""tests/test_optimizer_core_833.py — #833 θ 通道与宪法隔离。

覆盖：
  1. PARAM_SPEC 不含宪法键；validate_spec 拒绝宪法键
  2. SPSA 在合成凸函数上收敛（损失下降）
  3. replay_loss 好轨迹 < 坏轨迹（豆包型坏样本判负）
  4. make_proposal schema + 宪法键拒绝 + 提案只出文件不生效
"""
from __future__ import annotations

import json

import pytest

sys_path_setup = None  # noqa — conftest puts scripts/ on path in this repo


def test_spec_has_no_constitutional_keys():
    from optimizer_core import PARAM_SPEC, CONSTITUTIONAL_KEYS, validate_spec
    names = {name for name, *_ in PARAM_SPEC}
    assert not (names & CONSTITUTIONAL_KEYS)
    validate_spec(PARAM_SPEC)  # 默认 spec 必过
    with pytest.raises(ValueError):
        validate_spec([("proven_gate_required", 1.0, 0.0, 1.0)])


def test_spsa_converges_on_convex():
    from optimizer_core import spsa_optimize, SPSAConfig
    # 2-D 凸：L(θ) = (θ0-3)² + 2(θ1+1)²，最优 (3, -1)
    def loss(th):
        return (th["w_a"] - 3.0) ** 2 + 2.0 * (th["w_b"] + 1.0) ** 2

    spec = [("w_a", 0.0, -10.0, 10.0), ("w_b", 0.0, -10.0, 10.0)]
    theta0 = {n: d for n, d, lo, hi in spec}
    cfg = SPSAConfig(delta=0.3, alpha=0.9, alpha_tau=15.0,
                     iterations=150, seed=7)
    best, history = spsa_optimize(theta0, loss, spec, cfg)
    assert len(history) == cfg.iterations + 1  # 含初始点
    assert loss(best) < loss(theta0) * 0.05  # 显著下降（衰减步长后可达 0）


def test_spsa_bounds_clipped():
    from optimizer_core import spsa_step
    spec = [("w_x", 0.5, 0.0, 1.0)]
    th = {"w_x": 0.98}
    # 梯度方向把 θ 推出上界 → 必须裁剪
    th2 = spsa_step(th, lambda t: -t["w_x"], spec,
                    delta=0.5, alpha=0.4, rng_seed=3)
    assert 0.0 <= th2["w_x"] <= 1.0


def test_replay_loss_good_lt_bad():
    from optimizer_core import replay_loss
    good = [{"cost": 0.4, "false_abandon": 0, "gap": 0.1},
            {"cost": 0.5, "false_abandon": 0, "gap": 0.0}]
    bad = [{"cost": 3.0, "false_abandon": 1, "gap": 0.9}]  # 豆包型
    th = {"cost_weight": 1.0, "false_abandon_weight": 5.0, "gap_weight": 2.0}
    assert replay_loss(good, th) < replay_loss(bad, th)


def test_make_proposal_schema_and_constitution():
    from optimizer_core import make_proposal, CONSTITUTIONAL_KEYS
    p = make_proposal(
        theta_old={"w": 1.0}, theta_new={"w": 1.2},
        evidence={"missions": 12, "delta_loss": -0.3},
        base_sha="abc123")
    assert p["schema_version"] == "opt-proposal-v1"
    assert p["kind"] == "theta_tuning"
    assert p["base_sha"] == "abc123"
    assert not (set(p["theta_new"]) & CONSTITUTIONAL_KEYS)
    # 宪法键拒绝
    with pytest.raises(ValueError):
        make_proposal(theta_old={}, theta_new={"proven_gate_required": 0.0},
                      evidence={}, base_sha="x")
    # 提案可 JSON 序列化（文件面契约）
    json.dumps(p, ensure_ascii=False)


def test_proposal_roundtrip_file(tmp_path):
    from optimizer_core import make_proposal, write_proposal
    p = make_proposal(theta_old={"w": 1.0}, theta_new={"w": 1.1},
                      evidence={"missions": 3}, base_sha="s")
    path = tmp_path / "prop.json"
    write_proposal(path, p)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded == p
