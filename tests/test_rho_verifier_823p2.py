# -*- coding: utf-8 -*-
"""#823-P2 rho_t dense signal shadow suite (blueprint 7.2)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import rho_verifier as rv  # noqa: E402
import rho_checkpoint  # noqa: E402


def _mk_ws(tmp_path, pqs, claims=(), facts=None):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "task_spec.yaml").write_text(
        yaml.safe_dump({"primary_questions": pqs}, allow_unicode=True),
        encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": list(claims)}, allow_unicode=True),
        encoding="utf-8")
    (ws / "facts").mkdir(exist_ok=True)
    for name, body in (facts or {}).items():
        (ws / "facts" / name).write_text(body, encoding="utf-8")
    return ws


def _rows(ws, action):
    rows = []
    for p in sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("action") == action:
                    rows.append(r)
    return rows


def test_default_backend_is_deterministic(tmp_path):
    ws = _mk_ws(tmp_path, pqs=["find the packer family"])
    out = rv.get_backend().sample(ws)
    assert 0.0 <= out["rho"] <= 1.0
    assert out["backend"] == "deterministic"


def test_rho_pair_lands_in_ledger(tmp_path):
    ws = _mk_ws(tmp_path, pqs=["find the packer family"],
                facts={"F001.md": "handler 0x14002abcd allocates 0x150 "
                                  "size gate"})
    out = rv.sample_and_pair(ws)
    rows = _rows(ws, "rho_pair")
    assert len(rows) == 1
    d = rows[0]["detail"]
    if isinstance(d, str):
        d = json.loads(d)
    assert d["backend"] == "deterministic"
    assert d["z"] is None
    assert 0.0 <= out["rho"] <= 1.0


def test_settled_pairs_roundtrip_and_platt(tmp_path):
    ws = _mk_ws(tmp_path, pqs=["q one"])
    rv.sample_and_pair(ws, z=1.0)
    rv.sample_and_pair(ws, z=0.0)
    pairs = rv.pairs_from_ledger(ws)
    assert sorted(p["outcome"] for p in pairs) == [0.0, 1.0]
    w, b = rv.fit_platt(pairs)
    assert isinstance(w, float) and isinstance(b, float)


def test_platt_monotone_on_separable_pairs():
    pairs = [{"score": 0.2, "outcome": 0.0}, {"score": 0.8, "outcome": 1.0},
             {"score": 0.8, "outcome": 1.0}, {"score": 0.2, "outcome": 0.0}]
    w, b = rho_checkpoint.fit_platt(pairs)
    hi = rho_checkpoint.sigmoid(w * 0.8 + b)
    lo = rho_checkpoint.sigmoid(w * 0.2 + b)
    assert hi > lo


def test_platt_reexport_single_source():
    pairs = [{"score": 0.1, "outcome": 0.0}, {"score": 0.9, "outcome": 1.0},
             {"score": 0.9, "outcome": 1.0}, {"score": 0.1, "outcome": 0.0}]
    assert rv.fit_platt(pairs) == rho_checkpoint.fit_platt(pairs)


def test_llm_env_without_config_falls_back(tmp_path):
    import os
    ws = _mk_ws(tmp_path, pqs=["q one"])
    os.environ["KUNGLAO_RHO_BACKEND"] = "llm"
    try:
        out = rv.get_backend().sample(ws)
        assert out["backend"] == "deterministic"
    finally:
        os.environ.pop("KUNGLAO_RHO_BACKEND", None)


def test_attach_signals_mounts(tmp_path, monkeypatch):
    monkeypatch.delenv("KUNGLAO_VALUE_ALGO", raising=False)
    ws = _mk_ws(tmp_path, pqs=["find the packer family"])
    rho_checkpoint.attach_signals(ws, {"decision": "x"})
    assert len(_rows(ws, "rho_pair")) == 1
