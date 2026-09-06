# -*- coding: utf-8 -*-
"""posteriors.py — #106 两个概率对象（库层，纯函数 + 持久化）。

#97 重建卡的数据模型半张：公式层从此有随机变量——

  对象 1 — oracle case = Bernoulli。每个 `oracle/cases/*.yaml` 案例是一
  个 Bernoulli 变量（过/不过），先验 Beta(1,1)，观测 = runner 裁决。
  **runner 红绿是系统需要的唯一 reward 信号。** 案例 scaffold 态（N 个
  pending expected entry）随对象携带为 `pending_entries` 计数——只报告，
  不参与 Beta 更新（decomposition 目标另有记账层）。

  对象 2 — PQ hypothesis 层 = categorical。每个 primary_question 的
  candidates 变成竞争解释上的分布：先验 = 声明候选上的归一化权重；观测
  通道两条——`update_eliminate(name)`（eliminates_candidate，质量转移）
  与 `update_evidence(name, strength)`（keyword/source 类证据的
  prior-only 通道，#112 证据词表）。**PQ 熵从此可计算：H(categorical)
  前后对比。**

  持久层 — PosteriorLedger → `<ws>/runs/posteriors.yaml`，schema
  `posteriors-schema/1`（版本字段强制；未知版本显式 raise
  PosteriorSchemaError 响亮失败，不静默——no-backcompat 政策下读者必须
  能探测格式）。缺失→空、坏 YAML→空+告警字段（fail-open，与 #103
  分层一致：坏字节降级不阻塞）。

边界（issue #106 Scope）：本卡只交付对象定义 + 更新律 + 持久化 + 熵——
纯库、全测。谁消费它们做排序（#107/#108 的 decide/priority_ratio 接线）
不在此卡。全库确定性：Thompson 抽样的 rng 由调用方注入
`random.Random(seed)`，无全局状态。
"""
from __future__ import annotations

import math
import os
import random
from pathlib import Path

import yaml

SCHEMA_ID = "posteriors-schema/1"
LEDGER_REL = "runs/posteriors.yaml"

_ALPHA0 = 1.0  # Beta(1,1) 均匀先验
_BETA0 = 1.0


class PosteriorSchemaError(ValueError):
    """后验账本 schema 版本未知/缺失 — 响亮拒绝，不静默降级。"""


def entropy_bits(probs: list[float]) -> float:
    """H = -Σ p·log2 p（bit）。纯函数；零质量项跳过（0·log0 = 0）。"""
    h = 0.0
    for p in probs:
        if p < 0.0:
            raise ValueError(f"negative probability: {p!r}")
        if p > 0.0:
            h -= p * math.log2(p)
    return h


def _require_pos(name: str, v: float) -> float:
    fv = float(v)
    if not (fv > 0.0) or math.isinf(fv):
        raise ValueError(f"{name} must be a positive finite number, got {v!r}")
    return fv


class CasePosterior:
    """oracle case 的 Bernoulli 后验（Beta 共轭）。

    alpha/beta 即当前后验参数（构造默认 = Beta(1,1) 先验）；
    update(passed) 按闭式共轭更新：绿 +alpha，红 +beta。
    """

    def __init__(self, case_id: str, alpha: float = _ALPHA0,
                 beta: float = _BETA0, pending_entries: int = 0):
        self.case_id = str(case_id)
        self.alpha = _require_pos("alpha", alpha)
        self.beta = _require_pos("beta", beta)
        pe = int(pending_entries)
        if pe < 0:
            raise ValueError(f"pending_entries must be >= 0, got {pending_entries!r}")
        self.pending_entries = pe

    def update(self, passed: bool) -> None:
        """一次 runner 观测的共轭闭式更新（绿 +1 alpha / 红 +1 beta）。"""
        if passed:
            self.alpha += 1.0
        else:
            self.beta += 1.0

    def mean(self) -> float:
        """后验均值 alpha/(alpha+beta) — 通过率的当前估计。"""
        return self.alpha / (self.alpha + self.beta)

    def sample(self, rng: random.Random) -> float:
        """Thompson 抽样：Beta(alpha, beta) 一次采样。rng 由调用方注入。"""
        return rng.betavariate(self.alpha, self.beta)

    def to_dict(self) -> dict:
        return {"alpha": self.alpha, "beta": self.beta,
                "pending_entries": self.pending_entries}

    @classmethod
    def from_dict(cls, case_id: str, d: dict) -> "CasePosterior":
        if not isinstance(d, dict):
            raise ValueError(f"case {case_id!r}: payload must be a mapping")
        return cls(case_id, alpha=d["alpha"], beta=d["beta"],
                   pending_entries=d.get("pending_entries", 0))


class PQCategorical:
    """PQ hypothesis 层的 categorical 分布（竞争解释空间）。

    构造时归一化；update_eliminate 把候选质量清零后重归一；
    update_evidence 按 strength 乘概率后重归一（prior-only 通道）。
    """

    def __init__(self, pq_id: str, candidates: dict[str, float]):
        self.pq_id = str(pq_id)
        if not candidates:
            raise ValueError(f"PQ {pq_id!r}: candidate set must be non-empty")
        probs: dict[str, float] = {}
        for name, w in dict(candidates).items():
            fw = float(w)
            if not (fw >= 0.0) or math.isinf(fw):
                raise ValueError(
                    f"PQ {pq_id!r} candidate {name!r}: weight must be "
                    f"finite and >= 0, got {w!r}")
            probs[str(name)] = fw
        total = sum(probs.values())
        if total <= 0.0:
            raise ValueError(f"PQ {pq_id!r}: candidate weights sum to zero")
        self._probs: dict[str, float] = {k: v / total for k, v in probs.items()}

    @property
    def probs(self) -> dict[str, float]:
        """当前分布的只读快照（副本 — 调用方改不动内部状态）。"""
        return dict(self._probs)

    def _renormalize(self) -> None:
        total = sum(self._probs.values())
        if total <= 0.0:
            raise ValueError(
                f"PQ {self.pq_id!r}: update left zero total mass")
        self._probs = {k: v / total for k, v in self._probs.items()}

    def update_eliminate(self, name: str) -> None:
        """eliminates_candidate 观测：该候选清零，质量归其余竞争者。"""
        if name not in self._probs:
            raise KeyError(f"PQ {self.pq_id!r}: unknown candidate {name!r}")
        if len(self._probs) == 1:
            raise ValueError(
                f"PQ {self.pq_id!r}: cannot eliminate the last candidate")
        self._probs[name] = 0.0
        self._renormalize()

    def update_evidence(self, name: str, strength: float) -> None:
        """证据通道：strength>1 抬升 / <1 压低，重归一保持 Σp=1。"""
        if name not in self._probs:
            raise KeyError(f"PQ {self.pq_id!r}: unknown candidate {name!r}")
        fs = float(strength)
        if not (fs >= 0.0) or math.isinf(fs):
            raise ValueError(f"strength must be finite and >= 0, got {strength!r}")
        self._probs[name] *= fs
        self._renormalize()

    def entropy(self) -> float:
        """H(categorical)，bit — 熵差就是这次观测的信息增益。"""
        return entropy_bits(list(self._probs.values()))

    def argmax(self) -> str:
        """当前最大质量候选（并列取声明序首个 — 确定性）。"""
        return max(self._probs, key=lambda k: self._probs[k])

    def to_dict(self) -> dict:
        return {"candidates": dict(self._probs)}

    @classmethod
    def from_dict(cls, pq_id: str, d: dict) -> "PQCategorical":
        if not isinstance(d, dict) or not isinstance(d.get("candidates"), dict):
            raise ValueError(f"PQ {pq_id!r}: payload must carry candidates mapping")
        return cls(pq_id, d["candidates"])


class PosteriorLedger:
    """两个命名空间（cases/pqs）的后验账本，落 `<ws>/runs/posteriors.yaml`。

    load 容错谱系：文件缺失 → 空 ledger（不 degraded）；坏 YAML / 顶层
    形状坏 → 空 ledger + degraded=True + warnings（fail-open，冷启动
    不被坏字节卡死）；schema 版本缺失或未知 → PosteriorSchemaError
    （版本墙，响亮拒绝）。save 原子写（tmp + os.replace）。
    """

    def __init__(self, cases: dict[str, CasePosterior] | None = None,
                 pqs: dict[str, PQCategorical] | None = None,
                 degraded: bool = False, warnings: list[str] | None = None):
        self.cases: dict[str, CasePosterior] = dict(cases or {})
        self.pqs: dict[str, PQCategorical] = dict(pqs or {})
        self.degraded = bool(degraded)
        self.warnings: list[str] = list(warnings or [])

    # ---------- persistence ----------

    def to_doc(self) -> dict:
        return {
            "schema": SCHEMA_ID,
            "cases": {k: v.to_dict() for k, v in self.cases.items()},
            "pqs": {k: v.to_dict() for k, v in self.pqs.items()},
        }

    @classmethod
    def from_doc(cls, doc: dict) -> "PosteriorLedger":
        if doc.get("schema") != SCHEMA_ID:
            raise PosteriorSchemaError(
                f"posteriors ledger schema mismatch: expected "
                f"{SCHEMA_ID!r}, got {doc.get('schema')!r} — refusing to "
                f"read an unknown format (no-backcompat policy)")
        led = cls()
        for cid, d in (doc.get("cases") or {}).items():
            try:
                led.cases[str(cid)] = CasePosterior.from_dict(str(cid), d)
            except (KeyError, TypeError, ValueError) as exc:
                led.warnings.append(f"case {cid!r} skipped: {exc}")
        for pid, d in (doc.get("pqs") or {}).items():
            try:
                led.pqs[str(pid)] = PQCategorical.from_dict(str(pid), d)
            except (KeyError, TypeError, ValueError) as exc:
                led.warnings.append(f"pq {pid!r} skipped: {exc}")
        return led

    def save(self, ws) -> Path:
        """原子写（同目录 tmp + os.replace）；runs/ 缺失则建。"""
        path = Path(ws) / LEDGER_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(
            yaml.safe_dump(self.to_doc(), allow_unicode=True, sort_keys=True),
            encoding="utf-8")
        os.replace(tmp, path)
        return path

    @classmethod
    def load(cls, ws) -> "PosteriorLedger":
        path = Path(ws) / LEDGER_REL
        if not path.exists():
            return cls()
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            return cls(degraded=True,
                       warnings=[f"unreadable {LEDGER_REL}: {exc}"])
        if not isinstance(doc, dict):
            return cls(degraded=True,
                       warnings=[f"{LEDGER_REL}: top level is not a mapping"])
        try:
            return cls.from_doc(doc)
        except PosteriorSchemaError:
            raise
        except Exception as exc:  # 形状坏但 schema 合法 — 不该发生，兜底降级
            return cls(degraded=True,
                       warnings=[f"{LEDGER_REL}: malformed payload: {exc}"])
