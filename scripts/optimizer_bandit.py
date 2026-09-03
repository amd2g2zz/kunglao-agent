# -*- coding: utf-8 -*-
"""optimizer_bandit.py — #833 机制开关的 β-Bernoulli 后验记账。

arm = 机制×泳道（如 "infeasible|android"）。结算归因消费 ledger 行的
arm 字段（#818 schema）。输出降级队列 = 四阶段门的降级候选（不直接
生效——晋级/降级走 shadow→canary 管线）。
"""
from __future__ import annotations

_ALPHA0 = 1.0  # Beta(1,1) 均匀先验
_BETA0 = 1.0


class BetaPosterior:
    """arm → Beta(alpha, beta) 后验。线程不共享，纯 dict。"""

    def __init__(self):
        self.counts: dict = {}

    def update(self, arm: str, success: bool) -> None:
        a, b = self.counts.get(arm, (_ALPHA0, _BETA0))
        self.counts[arm] = (a + (1 if success else 0),
                            b + (0 if success else 1))

    def posterior(self, arm: str) -> float:
        a, b = self.counts.get(arm, (_ALPHA0, _BETA0))
        return a / (a + b)

    def pulls(self, arm: str) -> int:
        a, b = self.counts.get(arm, (_ALPHA0, _BETA0))
        return int(a + b - 2)

    def to_dict(self) -> dict:
        return {"counts": {k: list(v) for k, v in self.counts.items()}}

    @classmethod
    def from_dict(cls, d: dict) -> "BetaPosterior":
        bp = cls()
        bp.counts = {k: tuple(v) for k, v in (d.get("counts") or {}).items()}
        return bp


def attribute_rows(bp: BetaPosterior, rows: list) -> int:
    """ledger 行归因：带 arm 的已结算行（z ∈ {0,1}）更新后验。

    返回归因行数；无 arm 或 z 缺失的行跳过（不可归因 ≠ 失败）。
    """
    n = 0
    for r in rows or []:
        arm = r.get("arm")
        z = r.get("z")
        if arm and z in (0, 1):
            bp.update(str(arm), z == 1)
            n += 1
    return n


def demotion_queue(bp: BetaPosterior, floor: float = 0.5,
                   min_pulls: int = 8) -> list:
    """负 lift 臂队列（升序按后验）：四阶段门的降级候选，不直接生效。"""
    out = []
    for arm, (a, b) in sorted(bp.counts.items()):
        n = int(a + b - 2)
        if n >= min_pulls and a / (a + b) < floor:
            out.append(arm)
    return out
