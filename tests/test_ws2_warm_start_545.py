# -*- coding: utf-8 -*-
"""tests/test_ws2_warm_start_545.py — WS2 cross-task posterior store +
keyed consumption (#545) RED-first pins: the warm start.

The honest framing (EXP-WS2-A, experiments/exp-ws2-pooling.md — local-only,
never committed): leave-one-workspace-out replay over the 12 real
2026-10-07 workspaces changed NO ranking anywhere (0/12) because the corpus
carries exactly ONE family (hypothesis-falsification). The store lands as
the MECHANISM (warm start, keyed consumption, declared-ride propensity,
holdout firewall); the re-ranking claim stays unproven at current N and the
PR says so.

What is pinned here:

  1. warm start: a second workspace on the same family starts NON-FLAT at
     its first dispatch — the store's λ=0.25-tempered rows enter ONLY as
     anchor mass (the cell_posterior anchor face), and the candidate
     receipt carries the additive ``posterior_store`` block (traceable,
     逐句可归因).
  2. the store NEVER writes into local cells: the warm sample leaves the
     workspace's own q-cell log untouched (per-workspace log stays
     authoritative for local cells).
  3. keyed consumption: ``fold`` groups by the 4-dim ``arm_key`` column
     (dual-written since WS1 #543); old logs without arm_key fall back to
     method_family (the dual-write tolerance mirrored); ``family_mass``
     and therefore the termination alive-face keep reading by FAMILY
     (prefix face over arm keys).
  4. λ tempering is real: the pool masses are LAMBDA-scaled (imported
     from meta_arms, never duplicated).
  5. store-root resolution: env KUNGLAO_POSTERIOR_STORE overrides the
     default skill-dir patterns path; reads are tolerant (missing/corrupt
     = empty, fail-open with the canonical warn).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from e2e import checkpoints  # noqa: E402
from rlvr import meta_arms  # noqa: E402
from rlvr import q_cells  # noqa: E402
from rlvr import strategy_store  # noqa: E402

FAM_WARM = "kdf-chain-reconstruction"      # has store rows
FAM_COLD = "obfuscation-peeling"           # no store rows


def _store_rows(ws_id: str, n_fail: int) -> list[dict]:
    return [{
        "schema": strategy_store.STORE_SCHEMA,
        "ts": "2026-10-07T00:00:00Z",
        "workspace_id": ws_id,
        "arm_key": f"{FAM_WARM}|facts_snapshot|none|1",
        "method_family": FAM_WARM,
        "feature_key": "none",
        "fingerprint": "fp000011112222",
        "status": "TIMEOUT",
        "credit": 0.0,
        "censored": True,
        "facts_citing": 2,
        "propensity": 1.0,
        "phi_delta": None,
        "provenance": {"dispatch_id": f"C-{i:03d}"},
    } for i in range(1, n_fail + 1)]


@pytest.fixture
def store_root(tmp_path, monkeypatch):
    """An isolated posterior store holding warm rows from ANOTHER
    workspace (the leave-one-out shape: the workspace-under-test's own
    rows never enter its warm start)."""
    root = tmp_path / "posterior-store"
    root.mkdir()
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE", str(root))
    for row in _store_rows("ws-donor", 4):
        strategy_store.append_row(row)
    return root


# --------------------------------------------------------------- 1. warm start

def test_second_workspace_starts_warm_nonflat_and_traceable(
        tmp_path, store_root):
    """A fresh workspace's FIRST candidates are non-flat: the warm family
    borrows anchor mass from the store (alpha+beta > 2), the cold family
    stays the wide Beta(1,1) (alpha == beta == 1), and the warm family's
    receipt block names the exact store rows (traceable)."""
    ws = tmp_path / "ws-second"
    ws.mkdir()
    _fam, receipt = checkpoints._sample_envelope_family(ws)
    assert receipt is not None, "the first dispatch must sample"
    cands = receipt["candidates"]
    warm, cold = cands[FAM_WARM], cands[FAM_COLD]
    assert warm["alpha"] + warm["beta"] > 2.0, \
        "warm family must borrow store anchor mass at the first dispatch"
    assert cold["alpha"] == 1.0 and cold["beta"] == 1.0, \
        "a family with no store rows stays the wide Beta(1,1)"
    block = warm.get("posterior_store")
    assert isinstance(block, dict) and block.get("rows") == 4, \
        "the receipt must trace the warm mass to the store rows"
    assert "posterior_store" not in cold, \
        "a zero-mass pool never rides the receipt"


# ------------------------------------------------- 2. never writes local cells

def test_warm_read_never_writes_local_cells(tmp_path, store_root):
    ws = tmp_path / "ws-warm"
    ws.mkdir()
    checkpoints._sample_envelope_family(ws)
    log = ws / "runs" / "q-cell-log.jsonl"
    assert not log.exists() or not log.read_text(encoding="utf-8").strip(), \
        "the store read must never write into the local q-cell log"


# ------------------------------------------------------- 3. keyed consumption

def _obs(sig, fam, credit, arm_key=None):
    return {"schema": q_cells.OBS_SCHEMA, "ts": "2026-10-07T00:00:00Z",
            "source": "settlement", "signature_hash": sig,
            "method_family": fam, "claim": None, "agent": None,
            "credit": credit, "arm_key": arm_key}


def test_fold_groups_by_arm_key_and_family_mass_keeps_prefix_face():
    sig = "aaaa0000aaaa"
    rows = [
        _obs(sig, "famA", 1.0, arm_key="famA|full|replay|2"),
        _obs(sig, "famA", 0.0, arm_key="famA|minimal|none|1"),
        _obs(sig, "famA", 0.0, arm_key=None),  # legacy row, family fallback
    ]
    view = q_cells.fold(q_cells.InMemoryStore(rows))
    assert set(k[1] for k in view.cells) == {
        "famA|full|replay|2", "famA|minimal|none|1", "famA"}, \
        "cells must group by the 4-dim arm_key; family-less rows fall back"
    s, f = view.family_mass("famA")
    assert s == 1.0 and f == 2.0, \
        "family_mass pools every arm_key cell whose family part matches"


def test_cell_posterior_pools_the_legacy_fallback_cell():
    sig = "bbbb0000bbbb"
    view = q_cells.fold(q_cells.InMemoryStore(
        [_obs(sig, "famB", 1.0, arm_key=None)]))
    a, b = q_cells.cell_posterior(
        view, sig, "famB", arm_key="famB|full|replay|2")
    assert (a, b) == (2.0, 1.0), \
        "an arm_key lookup must pool the legacy family-keyed cell (tolerance)"


def test_old_logs_without_arm_key_fold_unchanged():
    sig = "cccc0000cccc"
    view = q_cells.fold(q_cells.InMemoryStore(
        [_obs(sig, "famC", 1.0), _obs(sig, "famC", 0.0)]))
    cell = view.cells[(sig, "famC")]
    assert cell.success == 1.0 and cell.failure == 1.0
    assert q_cells.cell_posterior(view, sig, "famC") == (2.0, 2.0)


# ------------------------------------------------------------ 4. λ tempering

def test_warm_pools_are_lambda_tempered(tmp_path, store_root):
    pools = strategy_store.warm_pools(tmp_path / "ws-any", [FAM_WARM])
    pool = pools[FAM_WARM]
    assert pool.rows == 4
    assert pool.failure == pytest.approx(meta_arms.LAMBDA * 4.0), \
        "cross-task rows enter at the LAMBDA temper, never full weight"
    assert pool.success == 0.0


# ------------------------------------------------------- 5. root resolution

def test_store_root_env_override_and_default(monkeypatch):
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE", "/tmp/ws2-alt-root")
    assert strategy_store.store_root() == Path("/tmp/ws2-alt-root")
    monkeypatch.delenv("KUNGLAO_POSTERIOR_STORE", raising=False)
    assert strategy_store.store_root() == \
        Path(strategy_store.__file__).resolve().parent / "patterns"


def test_store_read_tolerant_on_missing_and_corrupt(tmp_path, monkeypatch):
    root = tmp_path / "nope"
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE", str(root))
    assert strategy_store.load_rows(ws=None) == []
    root.mkdir()
    (root / strategy_store.STORE_REL).write_text(
        "{not json}\n"
        + json.dumps({"schema": "posterior-store/1",
                      "workspace_id": "w"}) + "\n",
        encoding="utf-8")
    rows = strategy_store.load_rows(ws=None)
    assert len(rows) == 1, "corrupt rows skip, valid rows survive"
