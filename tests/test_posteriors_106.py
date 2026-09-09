# -*- coding: utf-8 -*-
"""tests/test_posteriors_106.py — #106 two probability objects (library tier).

oracle case = Bernoulli (Beta posterior, runner red/green is the only
reward signal); PQ hypothesis = categorical over competing explanations
(elimination + prior-only evidence channel). Persistence = the
`runs/posteriors.yaml` posterior ledger (schema `posteriors-schema/1`).

Anti-fool assertions pinned by issue #106 acceptance:
  - Beta update on red/green changes the posterior per the closed form
  - elimination shifts categorical mass and entropy decreases strictly
  - ledger round-trips byte-for-byte field-equal; survives a simulated
    session restart
  - unknown schema version fails LOUDLY (PosteriorSchemaError), never
    silently
"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import posteriors as po  # noqa: E402

# 前置实验 4 候选序列（主会话实测 2.000→~1.922→1.585→1.000→0.000）
_PQ4 = {"alpha": 1.0, "beta": 1.0, "gamma": 1.0, "delta": 1.0}


# ---------- Beta 闭式验证 ----------

def test_beta_update_closed_form():
    c = po.CasePosterior("C-001", alpha=2.0, beta=3.0)
    c.update(True)
    assert (c.alpha, c.beta) == (3.0, 3.0)
    assert math.isclose(c.mean(), 3.0 / 6.0, abs_tol=1e-12)
    c.update(False)
    assert (c.alpha, c.beta) == (3.0, 4.0)
    assert math.isclose(c.mean(), 3.0 / 7.0, abs_tol=1e-12)


def test_beta_uniform_prior_default():
    c = po.CasePosterior("C-001")
    assert (c.alpha, c.beta) == (1.0, 1.0)
    assert math.isclose(c.mean(), 0.5, abs_tol=1e-12)


# ---------- 消除更新熵单调递减（前置实验序列） ----------

def test_eliminate_entropy_strictly_monotonic():
    pq = po.PQCategorical("PQ-1", dict(_PQ4))
    h0 = pq.entropy()
    assert math.isclose(h0, 2.0, abs_tol=1e-9)

    # 先验-only 证据通道压低 delta，再走消除链
    pq.update_evidence("delta", 0.4)
    h1 = pq.entropy()
    assert math.isclose(sum(pq.probs.values()), 1.0, abs_tol=1e-9)
    assert h1 < h0

    pq.update_eliminate("delta")
    h2 = pq.entropy()
    assert math.isclose(h2, math.log2(3), abs_tol=1e-9)
    assert h2 < h1

    pq.update_eliminate("gamma")
    h3 = pq.entropy()
    assert math.isclose(h3, 1.0, abs_tol=1e-9)
    assert h3 < h2


def test_eliminate_to_single_candidate_zero_entropy():
    pq = po.PQCategorical("PQ-1", dict(_PQ4))
    for name in ("alpha", "beta", "gamma"):
        pq.update_eliminate(name)
    # 置 0 语义：键保留、质量全归最后存活候选（issue 卡原文"置 0 后归一化"）
    assert set(pq.probs) == set(_PQ4)
    assert math.isclose(pq.probs["delta"], 1.0, abs_tol=1e-9)
    assert all(pq.probs[k] == 0.0 for k in ("alpha", "beta", "gamma"))
    assert pq.entropy() == 0.0


# ---------- 证据通道保持归一化 ----------

def test_update_evidence_keeps_normalization_and_direction():
    pq = po.PQCategorical("PQ-1", {"a": 0.5, "b": 0.3, "c": 0.2})
    pq.update_evidence("a", 3.0)
    assert math.isclose(sum(pq.probs.values()), 1.0, abs_tol=1e-9)
    assert pq.probs["a"] == max(pq.probs.values())  # strength>1 抬升
    pq.update_evidence("b", 0.1)
    assert math.isclose(sum(pq.probs.values()), 1.0, abs_tol=1e-9)
    assert pq.probs["b"] < pq.probs["c"]  # strength<1 压低


def test_categorical_constructor_normalizes_weights():
    pq = po.PQCategorical("PQ-1", {"x": 2.0, "y": 2.0})
    assert math.isclose(sum(pq.probs.values()), 1.0, abs_tol=1e-9)
    assert math.isclose(pq.entropy(), 1.0, abs_tol=1e-9)
    assert pq.argmax() in ("x", "y")


def test_argmax_picks_largest_mass():
    pq = po.PQCategorical("PQ-1", {"a": 0.2, "b": 0.5, "c": 0.3})
    assert pq.argmax() == "b"


# ---------- ledger round-trip + 容错/版本墙 ----------

def test_ledger_roundtrip_and_restart(tmp_path):
    led = po.PosteriorLedger()
    led.cases["C-001"] = po.CasePosterior(
        "C-001", alpha=3.0, beta=1.0, pending_entries=2)
    led.pqs["PQ-1"] = po.PQCategorical(
        "PQ-1", {"AES": 0.7, "ChaCha20": 0.3})

    led.save(tmp_path)
    back = po.PosteriorLedger.load(tmp_path)
    assert back.degraded is False
    assert back.warnings == []
    assert math.isclose(back.cases["C-001"].mean(), 0.75, abs_tol=1e-12)
    assert back.cases["C-001"].pending_entries == 2
    assert math.isclose(back.pqs["PQ-1"].probs["AES"], 0.7, abs_tol=1e-12)

    # 模拟会话重启后继续更新再落盘
    back.cases["C-001"].update(False)
    back.pqs["PQ-1"].update_eliminate("ChaCha20")
    back.save(tmp_path)
    again = po.PosteriorLedger.load(tmp_path)
    assert math.isclose(again.cases["C-001"].mean(), 3.0 / 5.0, abs_tol=1e-12)
    assert again.pqs["PQ-1"].entropy() == 0.0


def test_load_missing_file_is_empty_not_degraded(tmp_path):
    led = po.PosteriorLedger.load(tmp_path)
    assert led.cases == {} and led.pqs == {}
    assert led.degraded is False
    assert led.warnings == []


def test_bad_yaml_degrades_to_empty(tmp_path):
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "posteriors.yaml").write_text(
        "schema: [unclosed\n  bad", encoding="utf-8")
    led = po.PosteriorLedger.load(tmp_path)
    assert led.cases == {} and led.pqs == {}
    assert led.degraded is True
    assert led.warnings, "degraded load must carry the reason"


def test_unknown_schema_version_raises(tmp_path):
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "posteriors.yaml").write_text(
        yaml.safe_dump({"schema": "posteriors-schema/999",
                        "cases": {}, "pqs": {}}), encoding="utf-8")
    try:
        po.PosteriorLedger.load(tmp_path)
    except po.PosteriorSchemaError:
        pass
    else:
        raise AssertionError("unknown schema version must fail loudly")


def test_missing_schema_field_raises(tmp_path):
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "posteriors.yaml").write_text(
        yaml.safe_dump({"cases": {}, "pqs": {}}), encoding="utf-8")
    try:
        po.PosteriorLedger.load(tmp_path)
    except po.PosteriorSchemaError:
        pass
    else:
        raise AssertionError("missing schema field must fail loudly")


# ---------- Thompson sample 确定性 ----------

def test_thompson_sample_deterministic_same_seed():
    c = po.CasePosterior("C-001", alpha=7.0, beta=3.0)
    rng_a, rng_b = random.Random(2026), random.Random(2026)
    seq_a = [c.sample(rng_a) for _ in range(8)]
    seq_b = [c.sample(rng_b) for _ in range(8)]
    assert seq_a == seq_b
    assert all(0.0 <= x <= 1.0 for x in seq_a)
    assert len(set(seq_a)) > 1  # 真抽样，非常数


# ---------- pending_entries 不参与 Beta ----------

def test_pending_entries_do_not_touch_beta_mean():
    c0 = po.CasePosterior("C-001")
    c1 = po.CasePosterior("C-002", pending_entries=4)
    assert (c0.alpha, c0.beta) == (c1.alpha, c1.beta)
    assert c0.mean() == c1.mean()
    c1.update(True)
    assert math.isclose(c1.mean(), 2.0 / 3.0, abs_tol=1e-12)
    assert c1.pending_entries == 4  # 报告字段，不被动更新改写


# ---------- 模块级纯函数 + 边界 ----------

def test_entropy_bits_module_function():
    assert math.isclose(po.entropy_bits([1.0]), 0.0, abs_tol=1e-12)
    assert math.isclose(po.entropy_bits([0.5, 0.5]), 1.0, abs_tol=1e-12)
    assert math.isclose(po.entropy_bits([0.25] * 4), 2.0, abs_tol=1e-12)


def test_eliminate_last_candidate_rejected():
    pq = po.PQCategorical("PQ-1", {"only": 1.0})
    try:
        pq.update_eliminate("only")
    except ValueError:
        pass
    else:
        raise AssertionError("eliminating the last candidate leaves zero "
                             "mass — must be rejected")


def test_unknown_candidate_name_rejected():
    pq = po.PQCategorical("PQ-1", dict(_PQ4))
    for bad in (lambda: pq.update_eliminate("nope"),
                lambda: pq.update_evidence("nope", 1.0)):
        try:
            bad()
        except KeyError:
            pass
        else:
            raise AssertionError("unknown candidate must raise KeyError")


def test_schema_id_is_versioned():
    assert po.SCHEMA_ID == "posteriors-schema/1"
