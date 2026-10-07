# -*- coding: utf-8 -*-
"""tests/test_ws2_ablation_545.py — WS2 (#545) acceptance: the uniform-arm
ablation. Cutting the store (KUNGLAO_POSTERIOR_STORE → an empty root)
degrades a new workspace's first dispatch to the wide Beta(1,1) — the L2
ablation prediction ("no-L2 degrades-to-uniform").

Pins:

  1. with a warm store: first candidates borrow anchor mass (non-flat).
  2. store cut to an empty root: every candidate collapses to alpha ==
     beta == 1.0 and no ``posterior_store`` receipt block — the flat
     face the sampler had before WS2.
  3. a MISSING store root reads as empty (fail-open), same flat face.
  4. a corrupt store row is skipped and counted — never an exception
     into the sampler, never a fabricated pool.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from e2e import checkpoints  # noqa: E402
from rlvr import strategy_store  # noqa: E402

FAM = "kdf-chain-reconstruction"


def _seed_store(root: Path, ws_id: str, n: int) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for i in range(1, n + 1):
        strategy_store.append_row({
            "schema": strategy_store.STORE_SCHEMA,
            "ts": "2026-10-07T00:00:00Z",
            "workspace_id": ws_id,
            "arm_key": f"{FAM}|facts_snapshot|none|1",
            "method_family": FAM,
            "feature_key": "none",
            "fingerprint": "fp000011112222",
            "status": "DISPATCHED",
            "credit": 1.0,
            "censored": False,
            "facts_citing": 2,
            "propensity": 1.0,
            "phi_delta": None,
            "provenance": {"dispatch_id": f"C-{i:03d}"},
        })


def _flat(cands: dict) -> bool:
    return all(c["alpha"] == 1.0 and c["beta"] == 1.0
               and "posterior_store" not in c for c in cands.values())


def test_cutting_the_store_degrades_to_uniform(tmp_path, monkeypatch):
    """The acceptance ablation: store present -> warm; store cut -> the
    exact pre-WS2 flat face."""
    ws = tmp_path / "ws"
    ws.mkdir()
    warm_root = tmp_path / "store-warm"
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE", str(warm_root))
    _seed_store(warm_root, "ws-donor", 4)
    _fam, warm_receipt = checkpoints._sample_envelope_family(ws)
    assert warm_receipt is not None
    assert not _flat(warm_receipt["candidates"]), \
        "warm store must engage the anchor at the first dispatch"

    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE", str(tmp_path / "empty"))
    _fam2, cut_receipt = checkpoints._sample_envelope_family(ws)
    assert cut_receipt is not None
    assert _flat(cut_receipt["candidates"]), \
        "cutting the store must degrade the first dispatch to uniform " \
        "(the L2 ablation prediction)"


def test_missing_store_root_reads_as_empty(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE",
                       str(tmp_path / "never-created"))
    _fam, receipt = checkpoints._sample_envelope_family(ws)
    assert receipt is not None and _flat(receipt["candidates"])


def test_corrupt_store_rows_skip_and_count(tmp_path, monkeypatch, caplog):
    root = tmp_path / "store-corrupt"
    root.mkdir()
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE", str(root))
    (root / strategy_store.STORE_REL).write_text(
        "{broken json}\n", encoding="utf-8")
    assert strategy_store.load_rows(ws=None) == [], \
        "a corrupt store is an honest empty, never an exception"
