# -*- coding: utf-8 -*-
"""tests/test_mission_repin_868.py — #868 mission_ledger.repin delta API。

意愿类信号的可撤销语义：最后者赢 + 历史留痕 + answered 态保护
（re-pin 不得重置已答 PQ；移除的 PQ 连同作答一并移除）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import mission_ledger as ml  # noqa: E402


def _mk_ws(tmp_path):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "task_spec.yaml").write_text(yaml.safe_dump({
        "primary_questions": [{"id": p, "question": p}
                              for p in ("PQ-1", "PQ-2")]},
        allow_unicode=True), encoding="utf-8")
    ml.init(ws)
    # PQ-1 先答掉
    led = ml.load(ws)
    for p in led["mission"]["pqs"]:
        if p["id"] == "PQ-1":
            p.update(state="answered", coverage=1.0)
    ml._save(ws, led)
    return ws


def test_repin_add_remove_delta(tmp_path):
    ws = _mk_ws(tmp_path)
    ml.repin(ws, add=["PQ-3"], remove=["PQ-2"], note="sig-1")
    led = ml.load(ws)
    ids = [p["id"] for p in led["mission"]["pqs"]]
    assert ids == ["PQ-1", "PQ-3"]
    assert led["mission"]["history"][-1]["action"] == "repin"


def test_repin_preserves_answered_state(tmp_path):
    ws = _mk_ws(tmp_path)
    ml.repin(ws, add=[], remove=[])
    led = ml.load(ws)
    pq1 = next(p for p in led["mission"]["pqs"] if p["id"] == "PQ-1")
    assert pq1["state"] == "answered"     # 未被 re-pin 重置


def test_repin_remove_drops_answered_too(tmp_path):
    ws = _mk_ws(tmp_path)
    ml.repin(ws, add=["PQ-9"], remove=["PQ-1"], note="sig-2")
    led = ml.load(ws)
    ids = [p["id"] for p in led["mission"]["pqs"]]
    assert "PQ-1" not in ids and "PQ-9" in ids


def test_repin_idempotent_add(tmp_path):
    ws = _mk_ws(tmp_path)
    ml.repin(ws, add=["PQ-2"], remove=[])
    ml.repin(ws, add=["PQ-2"], remove=[])
    led = ml.load(ws)
    ids = [p["id"] for p in led["mission"]["pqs"]]
    assert ids.count("PQ-2") == 1


def test_repin_unknown_remove_is_noop(tmp_path):
    ws = _mk_ws(tmp_path)
    ml.repin(ws, add=[], remove=["PQ-404"], note="sig-3")
    led = ml.load(ws)
    assert len(led["mission"]["pqs"]) == 2
