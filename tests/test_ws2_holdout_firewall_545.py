# -*- coding: utf-8 -*-
"""tests/test_ws2_holdout_firewall_545.py — WS2 (#545) holdout firewall.

Two independent faces, both REQUIRED (defense in depth):

  1. WRITE face: ``strategy_store.append_row`` refuses BEFORE append any
     row whose serialized form carries a holdout unit-id (read from
     eval/v1/split.yaml — READ-only; the file is never written).
  2. LINT face: eval_split_lint hard-fails any holdout unit-id reaching
     a posterior-store.jsonl row under a prior_store_root (the
     schema-aware POSTERIOR_STORE_UNIT_ID class, on top of the existing
     whole-file text scan).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

import eval_split_lint  # noqa: E402
from rlvr import strategy_store  # noqa: E402


def _row(**over):
    row = {
        "schema": strategy_store.STORE_SCHEMA,
        "ts": "2026-10-07T00:00:00Z",
        "workspace_id": "e2e-ws-20261007-010648",
        "arm_key": "kdf-chain-reconstruction|facts_snapshot|none|1",
        "method_family": "kdf-chain-reconstruction",
        "feature_key": "none",
        "fingerprint": "fp000011112222",
        "status": "TIMEOUT",
        "credit": 0.5,
        "censored": True,
        "facts_citing": 2,
        "propensity": 1.0,
        "phi_delta": None,
        "provenance": {"dispatch_id": "C-004"},
    }
    row.update(over)
    return row


# ------------------------------------------------------------------ write face

def test_write_face_refuses_holdout_workspace_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE", str(tmp_path / "store"))
    out = strategy_store.append_row(
        _row(workspace_id="web-token-v1-holdout-ws"))
    assert out["appended"] is False
    assert "holdout" in str(out.get("reason")), \
        "a holdout unit-id must never reach the store (filter BEFORE append)"
    path = strategy_store.store_path()
    assert not path.exists() or \
        path.read_text(encoding="utf-8").strip() == "", \
        "the refused row must not be on disk"


def test_write_face_allows_clean_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE", str(tmp_path / "store"))
    out = strategy_store.append_row(_row())
    assert out["appended"] is True
    rows = strategy_store.load_rows(ws=None)
    assert len(rows) == 1 and rows[0]["provenance"]["dispatch_id"] == "C-004"
    # the full schema rides every row
    for field in ("schema", "ts", "workspace_id", "arm_key",
                  "method_family", "feature_key", "fingerprint", "status",
                  "credit", "censored", "facts_citing", "propensity",
                  "phi_delta", "provenance"):
        assert field in rows[0], f"store row missing {field}"


# ------------------------------------------------------------------- lint face

def _lint(patterns_root: Path) -> int:
    return eval_split_lint.main(["--patterns-root", str(patterns_root)])


def test_lint_hard_fails_poisoned_store_row(tmp_path, capsys):
    root = tmp_path / "patterns"
    root.mkdir()
    (root / strategy_store.STORE_REL).write_text(
        json.dumps(_row(workspace_id="web-token-v1-holdout-ws")) + "\n",
        encoding="utf-8")
    rc = _lint(root)
    assert rc == 1, "a poisoned store row must fail the lint"
    out = capsys.readouterr().out
    assert "POSTERIOR_STORE_UNIT_ID" in out, \
        "the schema-aware violation class must name the store row"


def test_lint_green_on_clean_store(tmp_path, capsys):
    root = tmp_path / "patterns"
    root.mkdir()
    (root / strategy_store.STORE_REL).write_text(
        json.dumps(_row()) + "\n", encoding="utf-8")
    assert _lint(root) == 0
    assert "clean" in capsys.readouterr().out
