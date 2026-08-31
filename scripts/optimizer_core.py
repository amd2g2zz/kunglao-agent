# -*- coding: utf-8 -*-
"""optimizer_core.py — #833 θ 数值通道（SPSA-on-replay）+ 宪法隔离。

只出提案，永不自动生效：本模块无任何写 value_config / 终态门 /
maker-checker 的路径（结构断言见 tests/test_optimizer_core_833.py）。

宪法隔离（蓝图 §8 安全网第 5 层）：CONSTITUTIONAL_KEYS 中的参数不可进入
PARAM_SPEC、不可进入提案——最坏坏提案也只产生低效派发权重，产生不了
未经验证的终态。

回放近似边界（诚实声明，见 openspec proposal）：replay_loss 对已结算
mission 的 (cost, false_abandon, gap) 三元组按 θ 重加权求和，不复刻
worker 决策序列；完整重放模拟器属 P4。
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Callable

SCHEMA_VERSION = "opt-proposal-v1"
THETA_SCHEMA = "opt-theta-v1"

# 宪法键：优化动作空间不可触碰（蓝图 §8 安全网第 5 层）。
CONSTITUTIONAL_KEYS = frozenset({
    "proven_gate_required",      # #819/#825 终态证据门
    "maker_checker_enabled",     # maker-checker 协议
    "fail_closed_defaults",      # 验证面 fail-closed 默认
    "terminal_verification",     # 无未经验证终态（六层不变量）
})

# θ 可优化参数（schema opt-theta-v1）：名/默认/下界/上界。
# 语义对齐 mission_ledger（β）、蓝图 §7（λ、K、N、权重、γ、Platt）。
PARAM_SPEC = [
    ("beta_blocked", 0.3, 0.0, 0.6),          # mission_ledger β
    ("zero_output_penalty", 1.0, 0.0, 5.0),   # λ·tokens 的 λ
    ("stall_k", 3.0, 2.0, 8.0),               # 主线停滞 K（离散化取整）
    ("fingerprint_n", 3.0, 2.0, 6.0),         # 零输出指纹 N
    ("mission_discount", 0.9, 0.5, 0.99),     # γ
    ("capability_bonus", 8.0, 0.0, 20.0),
    ("obstacle_bonus", 3.0, 0.0, 10.0),
    ("cost_weight", 1.0, 0.0, 10.0),
    ("false_abandon_weight", 5.0, 0.0, 20.0),
    ("gap_weight", 2.0, 0.0, 10.0),
    ("platt_w", 1.0, 0.0, 10.0),
    ("platt_b", 0.0, -5.0, 5.0),
    ("exploration_fraction", 0.1, 0.0, 0.4),
    ("park_credit", 0.3, 0.0, 0.6),           # blocked 部分信用
    ("coverage_bonus", 10.0, 0.0, 30.0),
    ("clawback_factor", 1.0, 0.5, 3.0),
    ("gap_hit_weight", 0.5, 0.0, 2.0),
    ("tier_weight", 0.3, 0.0, 2.0),
    ("voi_weight", 0.2, 0.0, 2.0),
    ("rho_floor", 0.15, 0.0, 0.6),
]
PARAM_NAMES = frozenset(n for n, *_ in PARAM_SPEC)


def validate_spec(spec) -> None:
    """spec 不得含宪法键；名/界必须良构。"""
    for name, default, lo, hi in spec:
        if name in CONSTITUTIONAL_KEYS:
            raise ValueError(f"constitutional key not optimizable: {name}")
        if lo >= hi:
            raise ValueError(f"bad bounds for {name}: [{lo}, {hi}]")
        if not (lo <= default <= hi):
            raise ValueError(f"default out of bounds for {name}")


def default_theta(spec=None) -> dict:
    spec = PARAM_SPEC if spec is None else spec
    return {name: default for name, default, _, _ in spec}


def spsa_step(theta: dict, loss_fn: Callable, spec, *,
              delta: float = 0.3, alpha: float = 0.5,
              rng_seed: int | None = None) -> dict:
    """一步 SPSA：Rademacher ±δ 扰动 → 差分梯度 → 步长 α，界内裁剪。"""
    rng = random.Random(rng_seed)
    names = [n for n, _, lo, hi in spec]
    bounds = {n: (lo, hi) for n, _, lo, hi in spec}
    sign = [1 if rng.random() < 0.5 else -1 for _ in names]
    tp = dict(theta)
    tm = dict(theta)
    for n, s in zip(names, sign):
        lo, hi = bounds[n]
        tp[n] = min(hi, max(lo, theta[n] + s * delta))
        tm[n] = min(hi, max(lo, theta[n] - s * delta))
    lp = loss_fn(tp)
    lm = loss_fn(tm)
    denom = 2.0 * delta
    out = {}
    for i, n in enumerate(names):
        g = (lp - lm) / denom * sign[i]
        lo, hi = bounds[n]
        out[n] = min(hi, max(lo, theta[n] - alpha * g))
    return out


def spsa_optimize(theta0: dict, loss_fn: Callable, spec, cfg) -> tuple:
    """迭代 SPSA（步长衰减 α_k = α₀/(1+k/τ)，标准 Spall 调度）。

    返回 (best_theta, history)；history 含初始点。
    """
    theta = dict(theta0)
    best = dict(theta)
    best_loss = loss_fn(theta)
    history = [best_loss]
    tau = max(1.0, float(getattr(cfg, "alpha_tau", 15.0)))
    for i in range(cfg.iterations):
        alpha_k = cfg.alpha / (1.0 + i / tau)
        theta = spsa_step(theta, loss_fn, spec,
                          delta=cfg.delta, alpha=alpha_k,
                          rng_seed=None if cfg.seed is None
                          else (cfg.seed + i))
        l = loss_fn(theta)
        history.append(l)
        if l < best_loss:
            best, best_loss = dict(theta), l
    return best, history


class SPSAConfig:
    def __init__(self, delta: float = 0.3, alpha: float = 0.9,
                 iterations: int = 150, seed: int | None = 11,
                 alpha_tau: float = 15.0):
        self.delta = delta
        self.alpha = alpha
        self.iterations = iterations
        self.seed = seed
        self.alpha_tau = alpha_tau


def replay_loss(missions: list, theta: dict) -> float:
    """规则近似回放损失（近似边界见模块 docstring）。

    missions: [{cost: float, false_abandon: 0|1, gap: 0..1}, ...]
    L = Σ (cost_weight·cost + false_abandon_weight·false_abandon
           + gap_weight·gap) / n
    """
    if not missions:
        return 0.0
    cw = theta.get("cost_weight", 1.0)
    fw = theta.get("false_abandon_weight", 5.0)
    gw = theta.get("gap_weight", 2.0)
    total = sum(m.get("cost", 0.0) * cw
                + m.get("false_abandon", 0) * fw
                + m.get("gap", 0.0) * gw for m in missions)
    return total / len(missions)


def make_proposal(theta_old: dict, theta_new: dict, evidence: dict,
                  base_sha: str, switches: dict | None = None) -> dict:
    """提案 JSON。宪法键出现即拒绝（引擎永远不产出可触碰终态门的提案）。"""
    for th in (theta_new, theta_old):
        bad = set(th) & CONSTITUTIONAL_KEYS
        if bad:
            raise ValueError(f"proposal touches constitutional keys: {sorted(bad)}")
    if switches:
        bad = {k for k in switches if k in CONSTITUTIONAL_KEYS}
        if bad:
            raise ValueError(f"proposal touches constitutional switches: {sorted(bad)}")
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "theta_tuning" if switches is None else "theta_and_switches",
        "theta_schema": THETA_SCHEMA,
        "base_sha": base_sha,
        "theta_old": theta_old,
        "theta_new": theta_new,
        "switches": switches or {},
        "evidence": evidence,
    }


def write_proposal(path, proposal: dict) -> None:
    Path(path).write_text(json.dumps(proposal, ensure_ascii=False, indent=1),
                          encoding="utf-8")
